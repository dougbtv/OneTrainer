import json
import os
import traceback

import torch
from safetensors.torch import load_file
from torch import Tensor

from modules.model.KandinskyModel import KandinskyModel
from modules.modelLoader.BaseModelLoader import BaseModelLoader
from modules.modelLoader.KandinskyModelLoader import KandinskyModelLoader
from modules.module.LoRAModule import LoRAModuleWrapper
from modules.util.TrainProgress import TrainProgress
from modules.util.ModelWeightDtypes import ModelWeightDtypes
from modules.util.enum.ModelType import ModelType


class KandinskyLoRAModelLoader(BaseModelLoader):
    def __init__(self):
        super(KandinskyLoRAModelLoader, self).__init__()

    @staticmethod
    def __get_rank(state_dict: dict) -> int:
        for name, state in state_dict.items():
            if "lora_down.weight" in name:
                return state.shape[0]

    @staticmethod
    def __init_lora(model: KandinskyModel, state_dict: dict[str, Tensor]):
        rank = KandinskyLoRAModelLoader.__get_rank(state_dict)

        model.unet_lora = LoRAModuleWrapper(
            orig_module=model.unet,
            rank=rank,
            prefix="lora_unet",
            module_filter=["attentions"],
        ).to(dtype=torch.float32)
        model.unet_lora.load_state_dict(state_dict)

    @staticmethod
    def __load_safetensors(model: KandinskyModel, lora_name: str):
        state_dict = load_file(lora_name)
        KandinskyLoRAModelLoader.__init_lora(model, state_dict)

    @staticmethod
    def __load_ckpt(model: KandinskyModel, lora_name: str):
        state_dict = torch.load(lora_name)
        KandinskyLoRAModelLoader.__init_lora(model, state_dict)

    @staticmethod
    def __load_internal(model: KandinskyModel, lora_name: str):
        with open(os.path.join(lora_name, "meta.json"), "r") as meta_file:
            meta = json.load(meta_file)
            train_progress = TrainProgress(
                epoch=meta['train_progress']['epoch'],
                epoch_step=meta['train_progress']['epoch_step'],
                epoch_sample=meta['train_progress']['epoch_sample'],
                global_step=meta['train_progress']['global_step'],
            )

        # embedding model
        pt_lora_name = os.path.join(lora_name, "lora", "lora.pt")
        safetensors_lora_name = os.path.join(lora_name, "lora", "lora.safetensors")
        if os.path.exists(pt_lora_name):
            KandinskyLoRAModelLoader.__load_ckpt(model, pt_lora_name)
        elif os.path.exists(safetensors_lora_name):
            KandinskyLoRAModelLoader.__load_safetensors(model, safetensors_lora_name)

        # optimizer
        try:
            model.optimizer_state_dict = torch.load(os.path.join(lora_name, "optimizer", "optimizer.pt"))
        except FileNotFoundError:
            pass

        # ema
        try:
            model.ema_state_dict = torch.load(os.path.join(lora_name, "ema", "ema.pt"))
        except FileNotFoundError:
            pass

        # meta
        model.train_progress = train_progress

    def load(
            self,
            model_type: ModelType,
            weight_dtypes: ModelWeightDtypes,
            base_model_name: str | None,
            extra_model_name: str | None
    ) -> KandinskyModel | None:
        stacktraces = []

        base_model_loader = KandinskyModelLoader()

        if base_model_name:
            model = base_model_loader.load(model_type, weight_dtypes, base_model_name, None)
        else:
            model = KandinskyModel(model_type=model_type)

        if extra_model_name:
            try:
                self.__load_internal(model, extra_model_name)
                return model
            except:
                stacktraces.append(traceback.format_exc())

            try:
                self.__load_ckpt(model, extra_model_name)
                return model
            except:
                stacktraces.append(traceback.format_exc())

            try:
                self.__load_safetensors(model, extra_model_name)
                return model
            except:
                stacktraces.append(traceback.format_exc())
        else:
            return model

        return model
