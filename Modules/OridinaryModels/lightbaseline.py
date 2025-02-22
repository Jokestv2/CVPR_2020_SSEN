import torch
import torch.nn as nn
from Modules.common.SSEN import SSEN
from Modules.Model_utils import make_residual_block, make_downsampling_network

class Baseline_light(nn.Module):
    def __init__(self, num_channel = 64, mode = "concat"):
        super(Baseline_light, self).__init__()
        # referenced by EDVR paper implementation code
        # https://github.com/xinntao/EDVR/blob/master/basicsr/models/archs/edvr_arch.py line 251
        self.downsampling_network = make_downsampling_network(layernum=2, in_channels=3, out_channels=64)
        self.lrfeature_scaler = nn.Conv2d(in_channels=3, out_channels=64, kernel_size=1, bias=False)
        #self.feature_extractor = make_residual_block(blocknum=5, input_channel=64, output_channel=64)
        self.feature_extractor = nn.Conv2d(in_channels=64, out_channels=64, kernel_size=3, padding=1, bias=False)
        self.feature_extractor2 = nn.Conv2d(in_channels=64,out_channels=64,kernel_size=3, padding=1, bias=False)
        self.SSEN_Network = SSEN(in_channels=num_channel,mode = mode)

        self.preprocessing_residual_block = nn.Conv2d(in_channels=128, out_channels=64, kernel_size=1, bias=False)
        self.residual_blocks = make_residual_block(blocknum=16, input_channel=64, output_channel=64)

        self.upscaling_4x = nn.Sequential(
            nn.Conv2d(in_channels=num_channel, out_channels=4*num_channel, kernel_size=3, padding=1, bias = False),
            nn.PixelShuffle(2),
            nn.Conv2d(in_channels=num_channel, out_channels=4*num_channel, kernel_size=3, padding=1, bias = False),
            nn.PixelShuffle(2),
        )

        self.outconv = nn.Conv2d(in_channels=num_channel, out_channels=3, kernel_size=3, padding=1, bias=False)


    def forward(self,input_lr, ref_input):
        ref_input = self.downsampling_network(ref_input)
        input_lr = self.lrfeature_scaler(input_lr)
        lr_feature_out = self.feature_extractor(input_lr)
        lr_feature_out = self.feature_extractor2(lr_feature_out)
        ref_feature_out = self.feature_extractor(ref_input)

        SSEN_out = self.SSEN_Network(lr_batch = lr_feature_out ,init_hr_batch = ref_feature_out)
        residual_input = torch.cat((lr_feature_out, SSEN_out), dim = 1)
        residual_input_scaled = self.preprocessing_residual_block(residual_input)
        out = self.residual_blocks(residual_input_scaled)
        out = torch.add(out,lr_feature_out)

        out = self.upscaling_4x(out)
        out = self.outconv(out)
        return out



if __name__ == "__main__":
    testmodel = Baseline(num_channel=256)
    model_layerlist = (list(testmodel.children()))
    print(model_layerlist)
   # torchsummary.summary(testmodel,(3,160,160),(3,160,160),device='cpu')
