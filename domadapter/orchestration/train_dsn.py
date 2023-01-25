import click
import pathlib
import gc
from domadapter.datamodules.mnli_dm import DataModuleSourceTarget
from domadapter.datamodules.sa_dm import SADataModuleSourceTarget
from domadapter.models.uda.dsn import DSN
from pytorch_lightning import Trainer
from pytorch_lightning.loggers import WandbLogger
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping
from pytorch_lightning import seed_everything
import json
import wandb


@click.command()
@click.option("--dataset-cache-dir", type=str, help="Cache directory for dataset.")
@click.option(
    "--source-target", type=str, help="Source and target domain in source_target format"
)
@click.option("--pretrained-model-name", type=str, help="PLM to be used from HF")
@click.option(
    "--padding", type=str, help="Add padding while tokenizing upto max length"
)
@click.option("--max-seq-length", type=str, help="seq length for tokenizer")
@click.option(
    "--num-classes",
    type=int,
    help="Number of classes for task adapter classification head",
)
@click.option("--bsz", type=int, help="batch size")
@click.option(
    "--data-module",
    type=str,
    help="data module on which trained model is to be trained (MNLI/SA)",
)
@click.option("--train-proportion", type=float, help="Train on small proportion")
@click.option("--dev-proportion", type=float, help="Validate on small proportion")
@click.option("--test-proportion", type=float, help="Test on small proportion")
@click.option(
    "--hidden-size", type=str, help="Hidden size of Linear Layer for downsampling"
)
@click.option("--exp-dir", type=str, help="Experiment directory to store artefacts")
@click.option("--seed", type=str, help="Seed for reproducibility")
@click.option("--lr", type=float, help="Learning rate for the entire model")
@click.option("--epochs", type=int, help="Number of epochs to run the training")
@click.option("--gpu", type=int, default=None, help="GPU to run the program on")
@click.option("--log-freq", type=int, help="Log wandb after how many steps")
@click.option(
    "--diff-weight",
    type=float,
    help="Scaling factor for difference loss",
)
@click.option("--sim-weight", type=float, help="Scaling factor for similarity loss")
@click.option(
    "--recon-weight",
    type=float,
    help="Scaling factor for reconstruction loss",
)
def train_dsn(
    bsz,
    dataset_cache_dir,
    pretrained_model_name,
    train_proportion,
    dev_proportion,
    test_proportion,
    hidden_size,
    num_classes,
    data_module,
    max_seq_length,
    padding,
    source_target,
    exp_dir,
    seed,
    log_freq,
    lr,
    epochs,
    gpu,
    diff_weight,
    sim_weight,
    recon_weight,
):
    dataset_cache_dir = pathlib.Path(dataset_cache_dir)
    exp_dir = pathlib.Path(exp_dir)
    exp_dir = exp_dir.joinpath(source_target, "DSN")

    if not exp_dir.is_dir():
        exp_dir.mkdir(parents=True)

    seed_everything(seed)

    hyperparams = {
        "bsz": bsz,
        "train_proportion": train_proportion,
        "dev_proportion": dev_proportion,
        "test_proportion": test_proportion,
        "source_target": source_target,
        "num_classes": int(num_classes),
        "dataset_cache_dir": str(dataset_cache_dir),
        "exp_dir": str(exp_dir),
        "hidden_size": int(hidden_size),
        "seed": seed,
        "learning_rate": lr,
        "epochs": int(epochs),
        "gpu": gpu,
        "pretrained_model_name": str(pretrained_model_name),
        "max_seq_length": int(max_seq_length),
        "padding": str(padding),
        "diff_weight": float(diff_weight),
        "sim_weight": float(sim_weight),
        "recon_weight": float(recon_weight),
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

    model = DSN(hyperparams)

    ###########################################################################
    # SETUP THE LOGGERS and Checkpointers
    ###########################################################################
    run_id = wandb.util.generate_id()
    exp_dir = exp_dir.joinpath(run_id)

    logger = WandbLogger(
        save_dir=exp_dir,
        id=run_id,
        project=project_name,
        job_type="DSN",
        group=source_target,
    )

    checkpoints_dir = exp_dir.joinpath("checkpoints")
    checkpoints_dir.mkdir(parents=True)

    checkpoint_callback = ModelCheckpoint(
        dirpath=str(checkpoints_dir),
        save_top_k=1,
        mode="max",
        monitor="source_val/f1",
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
    train_dsn()
