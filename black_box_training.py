import os
from resnet20 import resnet20
from resnet20_conv import resnet20_conv
import torch
from torch.autograd import Variable
from torchvision.datasets import CIFAR10
import torchvision.transforms as transforms
from torch.utils.data import DataLoader 
import argparse
import math
from tqdm import tqdm
import numpy as np
import time


parser = argparse.ArgumentParser()
parser.add_argument('--data', type=str, default='data/')
parser.add_argument('--load_dir', type=str, default='models_finetune/addernet_best.pt')
parser.add_argument('--save_dir', type=str, default='models_black_box_training/')
parser.add_argument('--log', default=False, action='store_true')
parser.add_argument('--gpu', type=int, default=2)
args = parser.parse_args()
os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)

os.makedirs(args.save_dir, exist_ok=True)
if args.log:
	time_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
	fo = open('training_' + time_str + '.log', 'w')
	fo_csv = open('training_' + time_str + '.csv', 'w')

acc_correct = 0
acc_eq = 0
acc_best = 0

transform_train = transforms.Compose([
	transforms.RandomCrop(32, padding=4),
	transforms.RandomHorizontalFlip(),
	transforms.ToTensor(),
	transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])

transform_test = transforms.Compose([
	transforms.ToTensor(),
	transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])

data_train = CIFAR10(args.data,
				   transform=transform_train,
				   download=True)
data_test = CIFAR10(args.data,
				  train=False,
				  transform=transform_test,
				  download=True)

data_train_loader = DataLoader(data_train, batch_size=128, shuffle=True, num_workers=8)
data_test_loader = DataLoader(data_test, batch_size=128, num_workers=0)

teacher = torch.load(args.load_dir)
teacher.eval()
student = resnet20_conv()
student.cuda()

criterion = torch.nn.CrossEntropyLoss().cuda()
optimizer = torch.optim.Adam(student.parameters(), lr=0.05)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, 400)

# def adjust_learning_rate(optimizer, epoch):
# 	"""For resnet, the lr starts from 0.1, and is divided by 10 at 80 and 120 epochs"""
# 	lr = 0.025 * (1+math.cos(float(epoch)/400*math.pi))
# 	for param_group in optimizer.param_groups:
# 		param_group['lr'] = lr
		
def train(epoch):
	global cur_batch_win
	student.train()
	loss_list, batch_list = [], []
	with tqdm(data_train_loader, desc="training") as pbar:
		for i, (images, labels) in enumerate(pbar, 1):
			images, labels = Variable(images).cuda(), Variable(labels).cuda()

			with torch.no_grad():
				output = teacher(images)
				pred = output.argmax(dim=-1)
	
			optimizer.zero_grad()
	
			output = student(images)
	
			loss = criterion(output, pred)

			loss_list.append(loss.data.item())
			batch_list.append(i)

			loss.backward()
			optimizer.step()

			pbar.set_description("Epoch: %d, Loss: %0.8f, lr: %0.6f" % (epoch, np.mean(loss_list), optimizer.param_groups[0]['lr']))
			if (i % 30 == 0 or i == len(data_train_loader)) and args.log:
				fo.write('[%d | %d] Loss: %f\n' % (epoch, i, loss.item()))

		print('Train - Epoch %d, Loss: %f' % (epoch, loss.data.item()))
		if args.log:
			fo.write('Train - Epoch %d, Loss: %f\n' % (epoch, loss.data.item()))

	scheduler.step()

	return loss.data.item()

 
def test():
	global acc_correct, acc_eq, acc_best
	student.eval()
	total_correct = 0
	total_eq = 0
	avg_loss = 0.0
	with torch.no_grad():
		for i, (images, labels) in enumerate(data_test_loader):
			images, labels = Variable(images).cuda(), Variable(labels).cuda()
			output = teacher(images)
			pred_teacher = output.argmax(dim=-1)
			output = student(images)
			avg_loss += criterion(output, pred_teacher) * images.shape[0]
			pred = output.data.max(1)[1]
			total_correct += pred.eq(labels.data.view_as(pred)).sum()
			total_eq += pred.eq(pred_teacher.data.view_as(pred)).sum()
 
	avg_loss /= len(data_test)
	acc_correct = float(total_correct) / len(data_test)
	acc_eq = float(total_eq) / len(data_test)
	if acc_best < acc_eq:
		acc_best = acc_eq
	print('Test Avg. Loss: %f, Acc_correct: %f, Acc_equal: %f' % (avg_loss.data.item(), acc_correct, acc_eq))
	if args.log:
		fo.write('Test Avg. Loss: %f, Acc_correct: %f, Acc_equal: %f\n' % (avg_loss.data.item(), acc_correct, acc_eq))
	return avg_loss.data.item(), acc_correct, acc_eq
 
 
def train_and_test(epoch):
	training_loss = train(epoch)
	testing_loss, testing_acc_correct, testing_acc_eq = test()
	if args.log:
		fo_csv.write('%f,%f,%f,%f\n' % (training_loss, testing_loss, testing_acc_correct, testing_acc_eq))
	return testing_acc_eq
 
 
def main():
	epoch = 400
	best_acc = 0
	for e in range(1, epoch + 1):
		testing_acc = train_and_test(e)
		if testing_acc > best_acc:
			best_acc = testing_acc
			torch.save(student, args.save_dir + 'addernet_best.pt')
		if e % 40 == 0 or e == epoch:
			torch.save(student, args.save_dir + 'addernet_{}.pt'.format(e))
		print('Best Accuracy: %f' % best_acc)
		if args.log:
			fo.write('Best Accuracy: %f\n' % best_acc)

if __name__ == '__main__':
	main()