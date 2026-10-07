import json
import joblib
import numpy as numpai
import pandas as panda
from pathlib import Path
import tensorflow as tf
from tensorflow.keras import layers, Model
from sklearn.preprocessing import MinMaxScaler

#Passo numero 1: A Configuração

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "events_up.csv"
OUTPUT_DIR = BASE_DIR / "agente"
OUTPUT_DIR.mkdir(exist_ok=True)

JANELA = 12 #12 Passos

GASES = [
    "CO"
]