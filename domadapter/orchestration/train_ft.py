import click
import pathlib
import gc
from domadapter.datamodules.mnli_dm import DataModuleSourceTarget
from domadapter.datamodules.sa_dm import SADataModuleSourceTarget
from domadapter.models.ft.finetune import FT
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping
from pytorch_lightning import seed_everything
import json
from pytorch_lightning.loggers import WandbLogger
import wandb


@click.command()
@click.option("--dataset-cache-dir", type=str, help="Cache directory for dataset.")
@click.option(
    "--source-target", type=str, help="Domain on which model will be finetuned"
)
@click.option("--pretrained-model-name", type=str, help="PLM to be used from HF")
@click.option(
    "--padding", type=str, help="Add padding while tokenizing upto max length"
)
@click.option("--max-seq-length", type=str, help="seq length for tokenizer")
@click.option("--bsz", type=int, help="batch size")
@click.option("--train-proportion", type=float, help="Train on small proportion")
@click.option("--test-proportion", type=float, help="Test on small proportion")
@click.option("--dev-proportion", type=float, help="Validate on small proportion")
@click.option(
    "--num-classes",
    type=int,
    help="Number of classes for PLM",
)
@click.option(
    "--data-module",
    type=str,
    help="data module on which trained model is to be trained (MNLI/SA)",
)
@click.option("--exp-dir", type=str, help="Experiment directory to store artefacts")
@click.option("--seed", type=str, help="Seed for reproducibility")
@click.option("--lr", type=float, help="Learning rate for the entire model")
@click.option("--epochs", type=int, help="Number of epochs to run the training")
@click.option("--gpu", type=int, default=None, help="GPU to run the program on")
@click.option("--log-freq", type=int, help="Log wandb after how many steps")
@click.option(
    "--gradient_clip_norm",
    type=float,
    help="Clips the graident if the norm is grater than this value",
    required=False,
    default=5.0,
)
def train_ft(
    bsz,
    dataset_cache_dir,
    pretrained_model_name,
    train_proportion,
    dev_proportion,
    test_proportion,
    max_seq_length,
    num_classes,
    padding,
    data_module,
    source_target,
    exp_dir,
    seed,
    log_freq,
    lr,
    epochs,
    gpu,
    gradient_clip_norm,
):
    dataset_cache_dir = pathlib.Path(dataset_cache_dir)
    exp_dir = pathlib.Path(exp_dir)
    exp_dir = exp_dir.joinpath("mnli_ft", source_target.split("_")[0])

    if not exp_dir.is_dir():
        exp_dir.mkdir(parents=True)

    seed_everything(seed)

    hyperparams = {
        "bsz": bsz,
        "train_proportion": train_proportion,
        "dev_proportion": dev_proportion,
        "test_proportion": test_proportion,
        "num_classes": int(num_classes),
        "source_target": source_target,
        "dataset_cache_dir": str(dataset_cache_dir),
        "exp_dir": str(exp_dir),
        "seed": seed,
        "learning_rate": lr,
        "epochs": int(epochs),
        "gpu": gpu,
        "pretrained_model_name": str(pretrained_model_name),
        "max_seq_length": int(max_seq_length),
        "padding": str(padding),
        "gradient_clip_norm": gradient_clip_norm,
    }

    ###########################################################################
    # Setup the dataset
    ###########################################################################
    if data_module == "mnli":
        dm = DataModuleSourceTarget(hyperparams)
        project_name = f"MNLI_{pretrained_model_name}"
    elif data_module == "sa":
        dm = SADataModuleSourceTarget(hyperparams)
        project_name = f"SA_{pretrained_model_name}"

    dm.prepare_data()

    model = FT(hyperparams)

    ###########################################################################
    # SETUP THE LOGGERS and Checkpointers
    ###########################################################################
    run_id = wandb.util.generate_id()
    exp_dir = exp_dir.joinpath(run_id)

    logger = WandbLogger(
        save_dir=exp_dir,
        id=run_id,
        project=project_name,
        job_type=source_target.split("_")[0],
        group="fine-tune",
    )

    checkpoints_dir = exp_dir.joinpath("checkpoints")
    checkpoints_dir.mkdir(parents=True)

    checkpoint_callback = ModelCheckpoint(
        dirpath=str(checkpoints_dir),
        save_top_k=1,
        mode="min",
        monitor="val/loss",
    )

    callbacks = [checkpoint_callback]

    trainer = Trainer(
        limit_train_batches=train_proportion,
        limit_val_batches=dev_proportion,
        limit_test_batches=test_proportion,
        callbacks=callbacks,
        terminate_on_nan=True,
        log_every_n_steps=log_freq,
        gpus=str(gpu),
        max_epochs=epochs,
        logger=logger,
        gradient_clip_val=gradient_clip_norm,
    )

    dm.setup("fit")
    train_loader = dm.train_dataloader()
    val_loader = dm.val_dataloader()
    trainer.fit(model, train_loader, val_loader)

    dm.setup("test")
    test_loader = dm.test_dataloader()
    trainer.test(model, test_loader)

    hparams_file = exp_dir.joinpath("hparams.json")

    with open(hparams_file, "w") as fp:
        json.dump(hyperparams, fp)

    del model
    gc.collect()


if __name__ == "__main__":
    train_ft()
