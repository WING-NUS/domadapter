import argparse
import torch
import numpy as np
import pandas as pd
from tqdm import tqdm
import glob
import gc
import os

from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

import plotly.express as px

from transformers import AutoTokenizer
from transformers import AutoModelWithHeads, AutoConfig

from datasets import load_dataset

# global variables
MAX_SEQ_LENGTH = 128
BATCH_SIZE = 8

parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--adapter', type=str,
                    help='directory containing checkpoint of adapter')
parser.add_argument('--source', type=str,
                    help='source CSV file whose representations are to be plotted')
parser.add_argument('--target', type=str,
                    help='target CSV file whose representations are to be plotted')
parser.add_argument('--reduction', type=str,
                    help='PCA or TSNE')

args = parser.parse_args()

'''
python adapter_representations.py \
--source "/Users/bhavitvyamalik/Desktop/work/domadapter/data/mnli/slate_travel/test_source.csv"\
--target "/Users/bhavitvyamalik/Desktop/work/domadapter/data/mnli/slate_travel/test_target.csv"\
--adapter "adapter"\
--reduction "TSNE"
'''

# get source domain name
source, target = args.source.split("/")[-2].split("_")
# source, target = args.source.split("/")[-2].split("_")[:2], args.source.split("/")[-2].split("_")[-1]
# source = "_".join(source)
# print(source)

# check if torch GPU available
if torch.cuda.is_available():
    device = torch.device("cuda")
else:
    device = torch.device("cpu")

# load model and tokenizer
config = AutoConfig.from_pretrained("bert-base-uncased", output_hidden_states=True)
model = AutoModelWithHeads.from_pretrained("bert-base-uncased", config=config)
tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")

# load adapter checkpoints and activate it
adapter_name = model.load_adapter(args.adapter)
# model.train_adapter([adapter_name])


output_dir = "pretrained"+adapter_name.split("domain_adapter")[-1]
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# put model on device
model.to(device)

# load csv source dataset
source_dataset = load_dataset("csv", data_files=[args.source])["train"]

# load csv target dataset
target_dataset = load_dataset("csv", data_files=[args.target])["train"]

# function to create temp directory to store representations
def prepare_dir():
    temp_dir = "temp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    else:
        # clear directory
        files = glob.glob('./temp/*')
        for f in files:
            os.remove(f)


def save_representations(dataset, name):
    prepare_dir()
    count = 0
    batch_text = []
    dictionary_list = []

    for i in tqdm(range(len(dataset))):
        # if(i<=500):
            if i % BATCH_SIZE == 0:  #batch size can be increased depending on your RAM
                batch_text.append((dataset["premise"][i], dataset["hypothesis"][i]))
                # batch_text.append(dataset["sentence"][i])

                encoding = tokenizer(batch_text, return_tensors='pt', padding='max_length', truncation=True, max_length=MAX_SEQ_LENGTH)
                input_ids = encoding['input_ids'].to(device)
                attention_mask = encoding['attention_mask'].to(device)
                outputs = model(input_ids, attention_mask)
                hidden_states = outputs["hidden_states"][1:]

                batch_text = []
                for example in range(len(hidden_states[0])):
                    for layer in range(0,12):
                        new_row = {'embeddings':hidden_states[layer][example][0].cpu().detach().numpy(), 'layers': layer+1}
                        dictionary_list.append(new_row)

                dictionary_list = np.save(f"./temp/batch_{count}", dictionary_list, allow_pickle=True)
                dictionary_list = []
                gc.collect()
                count += 1

            else:
                batch_text.append((dataset["premise"][i], dataset["hypothesis"][i]))
                # batch_text.append(dataset["sentence"][i])

    embeddings_list = []
    files = glob.glob("./temp/*.npy")

    for j in range(len(files)):
        alpha = np.load(f"./temp/batch_{j}.npy", allow_pickle = True)
        for i in range(len(alpha)):
            new_row = {'embeddings':alpha[i]["embeddings"], 'layers': alpha[i]["layers"], 'label': f"{name}"}
            embeddings_list.append(new_row)

    df = pd.DataFrame.from_dict(embeddings_list)
    return df


print("creating and saving representations for source")
source_df = save_representations(source_dataset, source)

print("creating and saving representations for target")
target_df = save_representations(target_dataset, target)

# concatenate source and target dataframes and change indexing
df = pd.concat([source_df, target_df])
df.reset_index(drop=True, inplace=True)

# filter dataframe by layers and create plots
for i in tqdm(range(1,13), desc="creating plots"):
    new_df = df[df['layers'] == i]
    new_df.reset_index(drop=True, inplace=True)
    mat = np.matrix([x for x in new_df.embeddings])

    if args.reduction == "PCA":
        pca = PCA(n_components=2, random_state=42)
        components = pca.fit_transform(mat)

    else:
        tsne = TSNE(n_components=2, random_state=42, n_jobs=-1)
        components = tsne.fit_transform(mat)

    fig = px.scatter(
        components, x=0, y=1, color=new_df['label'],
        labels={'color': 'label'}
    )
    fig.update_xaxes(visible=True, showticklabels=False, showgrid=False)
    fig.update_yaxes(visible=False, showticklabels=False, showgrid=False)
    if i == 1:
        fig.update_layout(
            autosize=False,
            width=1080,
            height=720,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis_title=f"Layer {i}",
            font=dict(
                size=26
            ),
            legend=dict(
                x=0,
                y=1,
                xanchor="left",
                yanchor="top",
                title=""
            ),)
    else:
        fig.update_layout(
            autosize=False,
            width=1080,
            height=720,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis_title=f"Layer {i}",
            font=dict(
                size=26
            ),
            showlegend=False)

    fig.write_image(f"./{output_dir}/layer_{i}.png")