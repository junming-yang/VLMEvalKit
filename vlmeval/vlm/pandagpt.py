import sys
import torch
import os.path as osp
import warnings
from .base import BaseModel
from accelerate import init_empty_weights, infer_auto_device_map, dispatch_model
import os

class PandaGPT(BaseModel):

    INSTALL_REQ = True
    INTERLEAVE = False

    def __init__(self, name, root=None, **kwargs):
        if root is None:
            warnings.warn('Please set `root` to PandaGPT code directory, which is cloned from here: ')
            sys.exit(-1)

        assert name == 'PandaGPT_13B'
        self.name = name
        sys.path.append(osp.join(root, 'code'))
        try:
            from model.openllama import OpenLLAMAPEFTModel
        except:
            raise ImportError(
                'Please first install PandaGPT and set the root path to use PandaGPT, '
                'which is cloned from here: https://github.com/yxuansu/PandaGPT. '
            )
        self.args = {
            'model': 'openllama_peft',
            'imagebind_ckpt_path': osp.join(root, 'pretrained_ckpt/imagebind_ckpt'),
            'vicuna_ckpt_path': osp.join(root, 'pretrained_ckpt/vicuna_ckpt/13b_v0'),
            'delta_ckpt_path': osp.join(root, 'pretrained_ckpt/pandagpt_ckpt/13b/pytorch_model.pt'),
            'stage': 2,
            'max_tgt_len': 512,
            'lora_r': 32,
            'lora_alpha': 32,
            'lora_dropout': 0.1,
        }
        model = OpenLLAMAPEFTModel(**self.args)
        delta_ckpt = torch.load(self.args['delta_ckpt_path'], map_location=torch.device('cpu'))
        model.load_state_dict(delta_ckpt, strict=False)
        torch.cuda.empty_cache()
        # self.model = model.eval().half().cuda()
        
        local_rank = int(os.environ.get('LOCAL_RANK', 0))
        device_num = torch.cuda.device_count()

        device_1 = local_rank
        device_2 = local_rank + device_num // 2

        device_map = infer_auto_device_map(
            model,
            max_memory={
                device_1: '32GiB',
                device_2: '32GiB'
            },
            no_split_module_classes=['LlamaDecoderLayer', 'VisionTransformer'])
        device_map['llama_model.base_model.model.lm_head'] = device_map['llama_proj'] = device_1
        print(device_map)
        model = dispatch_model(
            model,
            device_map=device_map).eval()
        self.model = model
        kwargs_default = {'top_p': 0.9, 'do_sample': False, 'max_tgt_len': 128, 'temperature': 0.001}
        kwargs_default.update(kwargs)
        self.kwargs = kwargs_default
        warnings.warn(f'Following kwargs received: {self.kwargs}, will use as generation config. ')

    def generate_inner(self, message, dataset=None):
        prompt, image_path = self.message_to_promptimg(message)
        struct = {
            'prompt': prompt,
            'image_paths': [image_path],
            'audio_paths': [],
            'video_paths': [],
            'thermal_paths': [],
            'modality_embeds': []
        }
        struct.update(self.kwargs)
        resp = self.model.generate(struct)
        return resp
