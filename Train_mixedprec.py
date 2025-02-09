import torch
import torch.nn as nn
import torch.optim as optim

from torch.utils.data import DataLoader

from Data_gen import Dataset_Vaild, Dataset_Train
from Modules.OridinaryModels.Baseline import Baseline
from Modules.OridinaryModels.Baseline_big import BigBaseline
from Modules.OridinaryModels.Baseline_small import Baseline_small
from Modules.OridinaryModels.lightbaseline import Baseline_light
from Modules.OridinaryModels.Baseline128 import Baseline128

from Modules.optimizer.cosine_annearing_with_warmup import CosineAnnealingWarmUpRestarts

import argparse
import numpy as np
import os

import tqdm
#from torch.utils.tensorboard import SummaryWriter
from Modules.Model_utils import L1_Charbonnier_loss


parser = argparse.ArgumentParser(description="RefSR Network with SSEN Training module")
parser.add_argument('--pre_trained', type = str, default=None, help = "path of pretrained modules")
parser.add_argument('--num_epochs', type = int, default = 2703, help = "Number of epochs")
parser.add_argument('--batch_size', type = int, default = 32, help = "Batch size")
parser.add_argument('--learning_rate', type = float, default=1e-4, help ="learning rate")
parser.add_argument('--gamma', type = float, default = 0.9, help = 'momentum of ADAM optimizer')
parser.add_argument('--pretrained_epoch', type=int, default=0, help ='pretrained models epoch')
parser.add_argument('--model_size', type = str, default="normal_concat", help = 'select model size')

if __name__ == "__main__":
    opt = parser.parse_args()

    TOTAL_EPOCHS = opt.num_epochs
    PRETRAINED_PATH = opt.pre_trained
  #  PRERESULTED_PATH = opt.pre_resulted
    BATCH_SIZE = opt.batch_size
    lr = opt.learning_rate
    gamma = opt.gamma
    PRETRAINED_EPOCH = opt.pretrained_epoch
    Modelsize = opt.model_size

    TrainDIR_PATH = "CUFED_SRNTT/input/"
    RefDIR_PATH = "CUFED_SRNTT/ref/"
    VaildDIR_PATH = "CUFED_SRNTT/CUFED5/"

    ResultSave_PATH = "Result_metrics"
    TrainedMODEL_PATH = "Trained_model"

    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')


    if Modelsize == "normal_concat":
        prefix_resultname = "normalModel_concat"
    elif Modelsize == "normal":
        prefix_resultname = "normalModel"
    elif Modelsize == "normal_cosine":
        prefix_resultname = "normalModel_cosine"
    elif Modelsize == "normal128":
        prefix_resultname = "normalModel_model128"
    elif Modelsize == "normal_cosine_concat":
        prefix_resultname = "normalModel_cosine_concat"
    elif Modelsize == "normal_light":
        prefix_resultname = "normalModel_light"
    elif Modelsize == "big":
        prefix_resultname = "bigModel"
    else:
        prefix_resultname = "smallModel"

    TrainedMODEL_PATH = os.path.join(TrainedMODEL_PATH,prefix_resultname)
    if not os.path.isdir(TrainedMODEL_PATH):
        os.mkdir(TrainedMODEL_PATH)

    Train_Dataset = Dataset_Train(dirpath_input=TrainDIR_PATH, dirpath_ref=RefDIR_PATH, upscale_factor=4)
    Vaild_Dataset = Dataset_Vaild(dirpath=VaildDIR_PATH, upscale_factor=4)

    Train_Dataloader = DataLoader(dataset=Train_Dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=2, drop_last=False, pin_memory=True)
    Vaild_Dataloader = DataLoader(dataset=Vaild_Dataset, batch_size=1, shuffle=False, num_workers=0, drop_last=True)

    if Modelsize == "normal_concat" or Modelsize == "normal_cosine_concat":
        print("load concat baseline module")
        Model = Baseline(mode= "concat")
    elif Modelsize == "normal" or Modelsize == "normal_cosine":
        print("load original baseline module")
        Model = Baseline()
    elif Modelsize == "normal128":
        print("load normal128 model")
        Model = Baseline128(mode = "concat")
    elif Modelsize == "normal_light":
        print("load light extraction model")
        Model = Baseline_light()
    elif Modelsize == "big":
        print("load big baseline module")
        Model = BigBaseline()
    else :
        print("load small baseline module")
        Model = Baseline_small()

    scaler = torch.cuda.amp.GradScaler()

    Model = nn.DataParallel(Model)
    Model = Model.to(device)

    optimizer = optim.Adam(Model.parameters(), lr=0, betas=(0.9, 0.999))

    if not Modelsize == "normal_cosine" and Modelsize == "normal_cosine_concat" and  Modelsize == "normal128":
        cosine_scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=TOTAL_EPOCHS)
    else:
        print("load cosinescheduler")
        cosine_scheduler = CosineAnnealingWarmUpRestarts(optimizer=optimizer, T_0 = 190, T_up=10, T_mult=2, eta_max=lr, gamma = gamma, last_epoch = PRETRAINED_EPOCH -1)
    
    criterion = L1_Charbonnier_loss().to(device)
    MSELoss_criterion = nn.MSELoss()
    loss_array_Train = np.zeros(TOTAL_EPOCHS)
    PSNR_array_Train = np.zeros(TOTAL_EPOCHS)
    PSNR_array_Vaild = np.zeros(TOTAL_EPOCHS)

    trainloader_len = len(Train_Dataloader)

    if PRETRAINED_EPOCH>0:
        checkpoint = torch.load(os.path.join(TrainedMODEL_PATH,prefix_resultname+"_epoch{}.pth".format(PRETRAINED_EPOCH)))
        Model = checkpoint['model']
        optimizer = checkpoint['optimizer']
        cosine_scheduler = checkpoint['cos_sched']

        Train_PSNR = np.load(os.path.join(ResultSave_PATH, prefix_resultname+"_Training_Average_PSNR.npy"))
        Train_loss = np.load(os.path.join(ResultSave_PATH, prefix_resultname+"_Training_Average_loss.npy"))

        for i in range(len(Train_PSNR)):
            PSNR_array_Train[i] = Train_PSNR[i]
            loss_array_Train[i] = Train_loss[i]

    for epoch in range(PRETRAINED_EPOCH,TOTAL_EPOCHS):
        Model.train()
        avg_PSNR = 0
        avg_loss = 0
        print("Training epoch : {}".format(epoch+1))
        for lr_image, hr_image, ref_image in tqdm.tqdm(Train_Dataloader, bar_format="{l_bar}{bar:40}{r_bar}"):
            lr_image, hr_image, ref_image = lr_image.to(device), hr_image.to(device), ref_image.to(device)
            optimizer.zero_grad()

            with torch.cuda.amp.autocast(): #apply mixed precision training
                sr_image = Model(lr_image, ref_image)
                loss = criterion(sr_image, hr_image)
            scaler.scale(loss).backward()
            avg_loss += loss
            MSELoss = MSELoss_criterion(sr_image, hr_image)
            avg_PSNR += 10 * torch.log10(1/MSELoss)
            scaler.step(optimizer)
            scaler.update()
            #optimizer.step()
 #           print("epoch {} training step : {}/{}".format(epoch + 1, i + 1, trainloader_len))


        cosine_scheduler.step()

        PSNR_array_Train[epoch] = avg_PSNR/len(Train_Dataloader)
        loss_array_Train[epoch] = loss/len(Train_Dataloader)

        print("Training average PSNR : {}, loss : {}".format(PSNR_array_Train[epoch], loss_array_Train[epoch]))

        if (epoch+1) % 50 == 0 or epoch == 0 :
            np.save(os.path.join(ResultSave_PATH,prefix_resultname+"_Training_Average_PSNR.npy"),PSNR_array_Train)
            np.save(os.path.join(ResultSave_PATH,prefix_resultname+"_Training_Average_loss.npy"),loss_array_Train)
            np.save(os.path.join(ResultSave_PATH,prefix_resultname+"_Vaild_Average_PSNR.npy"),PSNR_array_Vaild)

            checkpoint = {
                'model': Model,
                'optimizer': optimizer,
                'cos_sched': cosine_scheduler}
            torch.save(checkpoint, os.path.join(TrainedMODEL_PATH,prefix_resultname+"_epoch{}.pth".format(epoch+1)))
            #torch.save(Model.state_dict(), os.path.join(TrainedMODEL_PATH,prefix_resultname+"_epoch{}.pth".format(epoch+1)))

