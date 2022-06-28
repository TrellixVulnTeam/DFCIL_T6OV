import torch.nn as nn
import torch
from torchvision import transforms
import numpy as np
from torch.nn import functional as F
from PIL import Image
import torch.optim as optim
from myNetwork import network
from inversion_CIFAR100 import iCIFAR100
from torch.utils.data import DataLoader
from ResNet import resnet34_cbam
import pandas as pd
import os
import sys

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
def get_one_hot(target,num_class):
    one_hot=torch.zeros(target.shape[0],num_class).to(device)
    one_hot=one_hot.scatter(dim=1,index=target.long().view(-1,1),value=1.)
    return one_hot

class iCaRLmodel:

    def __init__(self,numclass,feature_extractor,batch_size,task_size,memory_size,epochs,learning_rate,prefix):

        super(iCaRLmodel, self).__init__()
        self.epochs=epochs
        self.learning_rate=learning_rate
        self.model = network(numclass,feature_extractor)
        self.exemplar_set = []
        self.class_mean_set = []
        self.numclass = numclass
        self.transform = transforms.Compose([#transforms.Resize(img_size),
                        transforms.ToTensor(),
                        transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761))])
        self.old_model = None

        self.train_transform = transforms.Compose([#transforms.Resize(img_size),
                            #transforms.RandomCrop((32,32),padding=4),
                            #transforms.RandomHorizontalFlip(p=0.5),
                            #transforms.ColorJitter(brightness=0.24705882352941178),
                            #transforms.ToTensor(),
                            #transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761))])
                            transforms.RandomCrop(32, padding=4),
                            transforms.RandomHorizontalFlip(),
                            transforms.ToTensor(),
                            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))])
        
        self.test_transform = transforms.Compose([#transforms.Resize(img_size),
                            transforms.ToTensor(),
                            #transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761))])
                            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))])

        self.classify_transform=transforms.Compose([transforms.RandomHorizontalFlip(p=1.),
                            #transforms.Resize(img_size),
                            transforms.ToTensor(),
                            #transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761))])
                            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))])

        
        self.train_dataset = iCIFAR100('dataset', transform=self.train_transform, download=True)
        self.test_dataset = iCIFAR100('dataset', test_transform=self.test_transform, train=False, download=True)

        self.batchsize = batch_size
        self.memory_size=memory_size
        self.task_size=task_size

        self.train_loader=None
        self.test_loader=None
        self.filename = None
        self.accuracies = []
        self.prefix = prefix
        self.best_acc = 0.0

    # get incremental train data
    # incremental
    def beforeTrain(self,task_id):
        self.model.eval()
        classes=[self.numclass-self.task_size,self.numclass]
        ## current task images
        self.train_loader,self.test_loader=self._get_train_and_test_dataloader(classes,task_id)
        if self.numclass>self.task_size:
            self.model.Incremental_learning(self.numclass)
        self.model.train()
        self.model.to(device)

    def _get_train_and_test_dataloader(self, classes,task_id):
        self.train_dataset.getTrainData(self.old_model,classes,self.filename,self.batchsize,task_id,self.prefix,self.task_size)
        self.test_dataset.getTestData(classes)
        train_loader = DataLoader(dataset=self.train_dataset,
                                  shuffle=True,
                                  batch_size=self.batchsize)

        test_loader = DataLoader(dataset=self.test_dataset,
                                 shuffle=True,
                                 batch_size=self.batchsize)

        return train_loader, test_loader
    
    # train model
    # compute loss
    # evaluate model
    def train(self):
        accuracy = 0.0
        opt = optim.SGD(self.model.parameters(), lr=self.learning_rate,weight_decay=0.00001)
        for epoch in range(self.epochs):
            if epoch == 48:
                if self.numclass==self.task_size:
                     print(1)
                     opt = optim.SGD(self.model.parameters(), lr=1.0/5, weight_decay=0.00001)
                else:
                     for p in opt.param_groups:
                         p['lr'] =self.learning_rate/ 5.0
                print("--------------------------")
                print("change learning rate:%.3f" % (self.learning_rate / 5))
                print("--------------------------")
            elif epoch == 62:
                if self.numclass>self.task_size:
                     for p in opt.param_groups:
                         p['lr'] =self.learning_rate/ 25
                         print("learning rate : ",p['lr'])
                else:
                     opt = optim.SGD(self.model.parameters(), lr=1.0/25, weight_decay=0.00001)
                print("--------------------------")
                print("change learning rate:%.3f" % (self.learning_rate / 25))
                print("--------------------------")

            #elif epoch == 80:
            elif epoch ==100:
                  if self.numclass==self.task_size:
                     opt = optim.SGD(self.model.parameters(), lr=1.0 /125, weight_decay=0.00001)
                  else:
                     for p in opt.param_groups:
                         p['lr'] =self.learning_rate/ 125
                  print("change learning rate:%.3f" % (self.learning_rate / 100.0))

            for step, (indexs, images, target) in enumerate(self.train_loader):
                images, target = images.to(device), target.to(device)
                #output = self.model(images)
                loss_value = self._compute_loss(indexs, images, target)
                opt.zero_grad()
                loss_value.backward()
                opt.step()
                if epoch == 69:
                    print("target: ",target)
                print('epoch:%d,step:%d,loss:%.3f' % (epoch, step, loss_value.item()))
            accuracy = self._test(self.test_loader, 1)

            print("*****************************")
            print('* epoch:%d,normal accuracy:%.3f *' % (epoch, accuracy))
            print("*****************************")

        return accuracy

    def _test(self, testloader, mode):
        if mode==0:
            print("compute NMS")
        self.model.eval()
        correct, total = 0, 0
        for setp, (indexs, imgs, labels) in enumerate(testloader):
            imgs, labels = imgs.to(device), labels.to(device)
            with torch.no_grad():
                outputs,_,_,_,_,_ = self.model(imgs) if mode == 1 else self.classify(imgs)
            predicts = torch.max(outputs, dim=1)[1] if mode == 1 else outputs
            correct += (predicts.cpu() == labels.cpu()).sum()
            total += len(labels)
        accuracy = 100.0 * correct / total
        #print(accuracy)
        self.model.train()
        return accuracy


    def _compute_loss(self, indexs, imgs, target):
        output,_,_,_,_,_ =self.model(imgs)
        target = get_one_hot(target, self.numclass)
        output, target = output.to(device), target.to(device)
        if self.old_model == None:
            return F.binary_cross_entropy_with_logits(output, target)
        else:
            old_output,_,_,_,_,_ = self.old_model(imgs)
            old_target = torch.sigmoid(old_output)
            old_task_size = old_target.shape[1]
            target[..., :old_task_size] = old_target
            return F.binary_cross_entropy_with_logits(output, target)


    # change the size of examplar
    def afterTrain(self,accuracy):
        self.model.eval()
        self.numclass+=self.task_size
        #self.compute_exemplar_class_mean()
        self.model.train()
        #KNN_accuracy=self._test(self.test_loader,0)
        #print("KNN_iCaRL accuracy"+str(KNN_accuracy.item()))
        self.accuracies.append(accuracy.item())
        self.filename = './'+self.prefix+str(self.task_size)+'/'+'task_'+str(int(self.numclass/self.task_size-1))
        os.makedirs(self.filename,exist_ok=True)
        pd.DataFrame(self.accuracies).to_csv(self.filename+"/top1_acc.csv",header=False,index=False)

        self.filename = self.filename+'_ResNet34.pt'
        torch.save(self.model,'./'+self.filename)
        self.old_model=torch.load('./'+self.filename)
        self.old_model.to(device)
        self.old_model.eval()
        

    def _construct_exemplar_set(self, images, m):
        class_mean, feature_extractor_output = self.compute_class_mean(images, self.transform)
        exemplar = []
        #ResNet layer4's dimension : 512
        now_class_mean = np.zeros((1, 512))
     
        for i in range(m):
            # shape batch_size*512
            ##20~40-
            x = class_mean - (now_class_mean + feature_extractor_output) / (i + 1)
            # shape batch_size
            x = np.linalg.norm(x, axis=1)
            index = np.argmin(x) # small distance norm distance
            now_class_mean += feature_extractor_output[index]
            exemplar.append(images[index])

        print("the size of exemplar :%s" % (str(len(exemplar))))
        self.exemplar_set.append(exemplar)

    def _reduce_exemplar_sets(self, m):
        for index in range(len(self.exemplar_set)):
            self.exemplar_set[index] = self.exemplar_set[index][:m]
            print('After sample delete, the size of class %d examplar: %s' % (index, str(len(self.exemplar_set[index]))))


    def Image_transform(self, images, transform):
        data = transform(Image.fromarray(images[0])).unsqueeze(0)
        for index in range(1, len(images)):
            data = torch.cat((data, self.transform(Image.fromarray(images[index])).unsqueeze(0)), dim=0)
        return data

    def compute_class_mean(self, images, transform):
        x = self.Image_transform(images, transform).to(device)
        feature_extractor_output = F.normalize(self.model.feature_extractor(x).detach()).cpu().numpy()
        class_mean = np.mean(feature_extractor_output, axis=0)
        return class_mean, feature_extractor_output


    def compute_exemplar_class_mean(self):
        self.class_mean_set = []
        for index in range(len(self.exemplar_set)):
            print("compute the class mean of %s"%(str(index)))
            exemplar=self.exemplar_set[index]
            class_mean, _ = self.compute_class_mean(exemplar, self.transform)
            class_mean_,_= self.compute_class_mean(exemplar,self.classify_transform)
            class_mean=(class_mean/np.linalg.norm(class_mean)+class_mean_/np.linalg.norm(class_mean_))/2
            self.class_mean_set.append(class_mean)

    def classify(self, test):
        result = []
        test = F.normalize(self.model.feature_extractor(test)).cpu().numpy()
        class_mean_set = np.array(self.class_mean_set)
        for target in test:
            x = target - class_mean_set
            x = np.linalg.norm(x, ord=2, axis=1)
            x = np.argmin(x)
            result.append(x)
        return torch.tensor(result)
