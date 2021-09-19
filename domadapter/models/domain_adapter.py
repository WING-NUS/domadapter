import torch
import pytorch_lightning as pl
from typing import Any, Optional, Dict
from transformers import AutoModelWithHeads
from transformers import AutoConfig
from domadapter.console import console
import torch.optim as optim
from torch.optim.lr_scheduler import ReduceLROnPlateau
from domadapter.divergences.cmd_divergence import CMD


class DomainAdapter(pl.LightningModule):

    def __init__(self, hparams:Optional[Dict[str, Any]] = None):
        """Domain Adapter LightningModule to train domain adapter using CMD as divergence.
        Args:
            hparams (Optional[Dict[str, Any]], optional): [description]. Defaults to None.
        """
        super(DomainAdapter, self).__init__()


        self.save_hyperparameters(hparams)

        # config
        self.config = AutoConfig.from_pretrained(self.hparams['pretrained_model_name'])
        # to get the layer wise pre-trained model outputs
        self.config.output_hidden_states = True

        # load the model weights
        with console.status(f"Loading {self.hparams['pretrained_model_name']} Model", spinner="monkey"):
            self.model = AutoModelWithHeads.from_pretrained(
                self.hparams['pretrained_model_name'], config=self.config
            )
        console.print(
            f"[green] Loaded {self.hparams['pretrained_model_name']} model"
        )

        # add adapter a new adapter
        self.model.add_adapter(self.hparams['domain_adapter_name'])
        # activate the adapter
        self.model.train_adapter(self.hparams['domain_adapter_name'])
        # object to compute the divergence
        self.criterion = CMD()


    def forward(self, input_ids, attention_mask=None):
        """Forward pass of the model"""
        # get the model output
        output = self.model(input_ids=input_ids, attention_mask=attention_mask)
        hidden_states = output.hidden_states
        return hidden_states


    # def configure_optimizers(self):
    #     return torch.optim.AdamW(
    #         params=self.model.parameters(),
    #         lr=self.hparams['learning_rate'],
    #         betas=self.hparams['betas'],
    #         eps=self.hparams['eps'],
    #         weight_decay=self.hparams['weight_decay'],
    #         # amsgrad=self.hparams['amsgrad'], not using this hparam
    #     )

    def configure_optimizers(self):

        optimizer = torch.optim.AdamW(
            params=self.model.parameters(),
            lr=self.hparams['learning_rate'],
            betas=self.hparams['betas'],
            eps=self.hparams['eps'],
            weight_decay=self.hparams['weight_decay'],
            # amsgrad=self.hparams['amsgrad'], not using this hparam
        )
        lr_scheduler = ReduceLROnPlateau(
            optimizer=optimizer,
            mode="min",
            factor=self.scheduler_factor,
            patience=self.scheduler_patience,
            threshold=self.scheduler_threshold,
            threshold_mode="rel",
            cooldown=self.scheduler_cooldown,
            eps=self.scheduler_eps,
            verbose=True,
        )
        return (
            [optimizer],
            [
                {
                    "scheduler": lr_scheduler,
                    "reduce_lr_on_plateau": True,
                    "monitor": "train/divergence",
                    "interval": "epoch",
                }
            ],
        )

    def training_step(self, batch, batch_idx):
        # concat the source and target data and pass it to the model
        input_ids = torch.cat((batch["source_input_ids"], batch["target_input_ids"]), axis=0)
        attention_mask = torch.cat((batch["source_attention_mask"], batch["target_attention_mask"]), axis=0)

        outputs = self(input_ids=input_ids, attention_mask=attention_mask)

        divergence = 0
        for num in range(len(outputs)):
            src_feature, trg_feature = torch.split(tensor=outputs[num], split_size_or_sections=batch['input_ids'].shape[0]//2, dim=0)
            divergence += self.criterion.calculate(src_hidden=src_feature, trg_hidden=trg_feature)

        self.log(
            "train/divergence",
            divergence,
            on_step=True,
            on_epoch=True,
            prog_bar=False,
            logger=True,
        )
        return {"train/divergence": divergence}

    def validation_step(self, batch, batch_idx):

        # concat the source and target data and pass it to the model
        input_ids = torch.cat((batch["source_input_ids"], batch["target_input_ids"]), axis=0)
        attention_mask = torch.cat((batch["source_attention_mask"], batch["target_attention_mask"]), axis=0)

        outputs = self(input_ids=input_ids, attention_mask=attention_mask)

        divergence = 0
        for num in range(len(outputs)):
            src_feature, trg_feature = torch.split(tensor=outputs[num], split_size_or_sections=batch['input_ids'].shape[0]//2, dim=0)
            divergence += self.criterion.calculate(src_hidden=src_feature, trg_hidden=trg_feature)

        # we can comment the logging here
        self.log(
            "val/divergence",
            value=divergence,
            on_step=True,
            on_epoch=True,
            prog_bar=False,
            logger=True,
        )
        return {"val/divergence": divergence}

    def validation_epoch_end(self, outputs):
        mean_divergenence = torch.stack([x['val/divergence'] for x in outputs]).mean()

        # this will show the mean div value across epoch
        self.log(
            "val/divergence",
            value=mean_divergenence,
            prog_bar=False,
            on_step=False,
            logger=True,
            on_epoch=True,
        )
        # need not to return
        # return {"val/divergence": mean_divergenence}






