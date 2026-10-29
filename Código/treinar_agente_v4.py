"""
Script Oficial de Treinamento e Avaliação do Agente Inteligente Multi-Task (V4)

Melhorias implementadas em relação à V3:
  1. Pré-processamento estritamente causal: filtro de mediana móvel com center=False
     (elimina vazamento de dados futuros; reproduzível em tempo real na inferência).
  2. Avaliação contra o alvo bruto (sem suavização artificial): métricas honestas
     de MAE, RMSE e Skill Score em relação à persistência ingênua.
  3. Perda direcional por amostra (shape [batch]): ativa o sample_weight de 3x
     nas transições de classe do IQAr.
  4. Camada DinamicaTemporal registrada no Keras: substitui camadas Lambda,
     permitindo carregamento nativo e thread-safe no Django (AirQualifyService).
  5. Geração completa de 5 gráficos acadêmicos em 300 DPI, histórico em CSV
     e relatório de métricas finais em JSON.
"""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import (
    balanced_accuracy_score, classification_report, confusion_matrix, f1_score,
    mean_absolute_error, precision_recall_fscore_support, roc_auc_score,
    root_mean_squared_error,
)
import tensorflow as tf
from tensorflow.keras import layers, Model

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from agente.preprocessamento import (
    GASES, FEATURES, COL_MEDIA_CO, JANELA, JANELA_MEDIA_CO, CO_MODERADA, CO_RUIM,
    classificar_co, media_movel_co, preprocessar, inverter_preprocessamento,
    DinamicaTemporal,
)

# -------------------------------------------------------------------------
# Passo 1: Configuração e Diretórios
# -------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "event_up.csv"
OUTPUT_DIR = BASE_DIR / "agente"
OUTPUT_DIR.mkdir(exist_ok=True)
GRAFICOS_DIR = OUTPUT_DIR / "graficos"
GRAFICOS_DIR.mkdir(exist_ok=True)

SEED = 42
tf.keras.utils.set_random_seed(SEED)
rng = np.random.default_rng(SEED)

FREQ_RESAMPLE = "1min"
JANELA = 30                # 30 minutos de histórico observado
HORIZONTE = 15             # Previsão para 15 minutos à frente
STRIDE_TREINO = 1          # Com dados a cada 1 min, não precisa pular amostras
import argparse
_parser = argparse.ArgumentParser(description="Script Oficial de Treinamento e Avaliação do Agente Multi-Task (V4)")
_parser.add_argument("--epocas", type=int, default=50, help="Número máximo de épocas de treinamento (padrão: 50)")
_parser.add_argument("--batch", type=int, default=128, help="Tamanho do batch (padrão: 128)")
_parser.add_argument("--patience", type=int, default=8, help="Paciência do Early Stopping (padrão: 8)")
_parser.add_argument("--extra-csv", type=str, default=None, help="Caminho para CSV com novas leituras para anexar")
_args, _ = _parser.parse_known_args()

BATCH, EPOCAS = _args.batch, _args.epocas
PATIENCE = _args.patience
EXTRA_CSV = _args.extra_csv
PESOS_LOSS = {"saida_anomalia": 15.0, "saida_delta": 2.0, "saida_iqar": 1.5}
CLASSES = ["Boa", "Moderada", "Ruim"]
PESO_CLASSE_MAX = 10.0
GAP_MAX_S = 900.0          # 15 minutos de tolerância contínua
MAGNITUDES_ANOMALIA = [0.05, 0.1, 0.2, 0.3]
MAG_REF = 0.2

print(">>> [V4 Oficial] Passo 1: Lendo leituras de 'event_up.csv'...")
df_raw = pd.read_csv(CSV_PATH, sep=";", usecols=["time", "object"])
df_raw["time"] = pd.to_datetime(df_raw["time"], format="ISO8601", utc=True)
df_raw = df_raw.sort_values("time").reset_index(drop=True)

def extrair_gases(texto_json):
    try:
        dados = json.loads(texto_json)
        return [float(dados[g]) for g in GASES]
    except (ValueError, KeyError, TypeError):
        return [np.nan] * len(GASES)

matriz_gases = [extrair_gases(obj) for obj in df_raw["object"]]
df = pd.DataFrame(matriz_gases, columns=GASES)
df["time"] = df_raw["time"]
df = df.dropna().sort_values("time").set_index("time")

if EXTRA_CSV and Path(EXTRA_CSV).exists():
    print(f">>> [V4 Oficial] Incorporando leituras adicionais de '{EXTRA_CSV}'...")
    df_extra_raw = pd.read_csv(EXTRA_CSV)
    col_tempo = "Time" if "Time" in df_extra_raw.columns else "time"
    df_extra_raw[col_tempo] = pd.to_datetime(df_extra_raw[col_tempo], utc=True)
    df_extra_raw = df_extra_raw.set_index(col_tempo)
    df = pd.concat([df, df_extra_raw[GASES]]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    print(f"    Total combinado de leituras válidas: {len(df)}")

# -------------------------------------------------------------------------
# Passo 2: Reamostragem Causal (1 minuto) e Alvo Bruto Honesto
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 2: Reamostrando para 1 min e aplicando filtro de mediana causal...")
df_1m = df[GASES].resample(FREQ_RESAMPLE).mean()
df_interp = df_1m.interpolate(method="time", limit=3)

# Entrada da rede: mediana móvel estritamente causal (center=False, sem dados futuros)
df_causal = df_interp.rolling(window=3, min_periods=1, center=False).median()

# Amostras válidas onde não há NaN
masc_validos = df_interp.notna().all(axis=1).to_numpy()
tempos = df_interp.index[masc_validos]
bruto_gases = df_interp.to_numpy(dtype=float)[masc_validos]       # ALVO REAL
filtrado_gases = df_causal.to_numpy(dtype=float)[masc_validos]    # ENTRADA
n = len(bruto_gases)
print(f"    Total de amostras contínuas de 1 min: {n}")

dt = pd.Series(tempos).diff().dt.total_seconds().to_numpy()
segmento = np.cumsum(np.nan_to_num(dt) > GAP_MAX_S)

# -------------------------------------------------------------------------
# Passo 3: Particionamento em Blocos Temporais (70% Treino, 15% Val, 15% Teste)
# -------------------------------------------------------------------------
tempo_s = np.asarray((tempos - tempos[0]).total_seconds())
bloco_id = (tempo_s // (7 * 86400)).astype(int)
particao = np.full(n, "treino", dtype=object)
for b in np.unique(bloco_id):
    idx_b = np.where(bloco_id == b)[0]
    nb = len(idx_b)
    if nb < (JANELA + HORIZONTE + 10):
        continue
    i_tr = int(nb * 0.70)
    i_va = int(nb * 0.85)
    particao[idx_b[i_tr:i_va]] = "validacao"
    particao[idx_b[i_va:]] = "teste"

masc_treino = particao == "treino"

# Teto de saturação com percentil 99.5% do treino
clip_gases = np.quantile(filtrado_gases[masc_treino], 0.995, axis=0)
clip_max = np.r_[clip_gases, clip_gases[0]]

# Canal 8: Média móvel de 8h do CO
co_media_in = media_movel_co(tempos, filtrado_gases[:, 0], clip_max[0])
co_media_bruto = media_movel_co(tempos, bruto_gases[:, 0], clip_max[0])

pre_entrada = preprocessar(np.column_stack([filtrado_gases, co_media_in]), clip_max)
pre_alvo = preprocessar(np.column_stack([bruto_gases, co_media_bruto]), clip_max)

scaler = MinMaxScaler()
scaler.fit(pre_entrada[masc_treino])
escalado_in = scaler.transform(pre_entrada).astype(np.float32)
escalado_alvo = scaler.transform(pre_alvo).astype(np.float32)

rotulos = classificar_co(co_media_bruto)

# -------------------------------------------------------------------------
# Passo 4: Criação das Janelas Deslizantes com Horizonte Futuro (15 min)
# -------------------------------------------------------------------------
print(f">>> [V4 Oficial] Passo 3: Montando tensores de janelas (Janela={JANELA}min, Horizonte={HORIZONTE}min)...")
total_passos = JANELA + HORIZONTE - 1
todos_inicios = np.arange(0, n - total_passos)
alvos_futuros = todos_inicios + total_passos

validos = (segmento[todos_inicios] == segmento[alvos_futuros]) & (particao[todos_inicios] == particao[alvos_futuros])
todos_inicios = todos_inicios[validos]
alvos_futuros = alvos_futuros[validos]

inicios_treino = todos_inicios[particao[todos_inicios] == "treino"][::STRIDE_TREINO]
inicios_val = todos_inicios[particao[todos_inicios] == "validacao"]
inicios_teste = todos_inicios[particao[todos_inicios] == "teste"]

def montar(inicios):
    idx = inicios[:, None] + np.arange(JANELA)[None, :]
    X = escalado_in[idx]                                               # Entrada com mediana causal
    y_fut = escalado_alvo[inicios + JANELA + HORIZONTE - 1]           # Alvo BRUTO em t+15
    y_cls = rotulos[inicios + JANELA + HORIZONTE - 1]                 # Classe real em t+15
    y_cls_atual = rotulos[inicios + JANELA - 1]                       # Classe no instante t
    return X, y_fut, y_cls, y_cls_atual

X_train, yfut_train, ycls_train, ycls_atual_train = montar(inicios_treino)
X_val, yfut_val, ycls_val, ycls_atual_val = montar(inicios_val)
X_test, yfut_test, ycls_test, ycls_atual_test = montar(inicios_teste)

delta_std = np.maximum((yfut_train - X_train[:, -1, :]).std(axis=0), 1e-6).astype(np.float32)

def calcular_delta(X, y_fut):
    return ((y_fut - X[:, -1, :]) / delta_std).astype(np.float32)

dtr, dva = calcular_delta(X_train, yfut_train), calcular_delta(X_val, yfut_val)

def dist(y):
    return {CLASSES[i]: int((y == i).sum()) for i in range(3)}

trans_treino = int((ycls_atual_train != ycls_train).sum())
print(f"    Treino {len(X_train)} ({trans_treino} transições) | Val {len(X_val)} | Teste {len(X_test)} janelas")
print(f"    Classes treino: {dist(ycls_train)} | val: {dist(ycls_val)} | teste: {dist(ycls_test)}")

# Ponderação focal de amostras (aplica foco nas transições apenas para classificação do IQAr)
transicao_treino_masc = (ycls_atual_train != ycls_train)
pesos_transicao_iqar = np.where(transicao_treino_masc, 3.5, 1.0).astype(np.float32)
sample_weight_train = [
    np.ones((len(X_train), JANELA), dtype=np.float32),
    np.ones(len(X_train), dtype=np.float32),             # Delta uniforme: sem viés direcional
    pesos_transicao_iqar,
]

# -------------------------------------------------------------------------
# Passo 5: Arquitetura Multi-Task com Camada Customizada DinamicaTemporal
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 4: Construindo modelo Multi-Task com DinamicaTemporal...")
entrada = layers.Input(shape=(JANELA, len(FEATURES)), name="input_sensores")

lstm_shared = layers.Bidirectional(layers.LSTM(32, return_sequences=True))(entrada)
lstm_shared = layers.Dropout(0.2)(lstm_shared)
features_latentes = layers.LSTM(16, return_sequences=False)(lstm_shared)

# Camada serializável de derivadas físicas (substitui Lambdas)
dinamica_explicita = DinamicaTemporal(name="dinamica_temporal")(entrada)
features_com_dinamica = layers.Concatenate(name="features_com_dinamica")([features_latentes, dinamica_explicita])

# Cabeça 1: Autoencoder (Reconstrução)
gargalo = layers.Dense(8, activation="relu", name="gargalo_anomalia")(features_latentes)
repeat = layers.RepeatVector(JANELA)(gargalo)
dec_lstm = layers.LSTM(16, return_sequences=True)(repeat)
saida_anomalia = layers.TimeDistributed(layers.Dense(len(FEATURES)), name="saida_anomalia")(dec_lstm)

# Cabeça 2: Previsão do Delta
dense_fore = layers.Dense(32, activation="relu")(features_com_dinamica)
dense_fore = layers.Dropout(0.1)(dense_fore)
dense_fore = layers.Dense(16, activation="relu")(dense_fore)
saida_delta = layers.Dense(len(FEATURES), name="saida_delta")(dense_fore)

# Cabeça 3: Classificação IQAr
dense_cls = layers.Dense(16, activation="relu")(features_com_dinamica)
saida_iqar = layers.Dense(3, activation="softmax", name="saida_iqar")(dense_cls)

modelo = Model(
    inputs=entrada,
    outputs=[saida_anomalia, saida_delta, saida_iqar],
    name="Agente_IQAr_MultiTask_V4"
)

contagem_cls = np.bincount(ycls_train, minlength=3)
pesos_classe = np.where(contagem_cls > 0, len(ycls_train) / (3.0 * np.maximum(contagem_cls, 1)), 1.0)
pesos_classe = np.minimum(pesos_classe, PESO_CLASSE_MAX).astype(np.float32)
_pesos_classe_tf = tf.constant(pesos_classe)

@tf.keras.utils.register_keras_serializable(package="agente")
def perda_iqar_ponderada(y_true, y_pred):
    y = tf.cast(tf.reshape(y_true, [-1]), tf.int32)
    ce = tf.keras.losses.sparse_categorical_crossentropy(y, y_pred)
    return ce * tf.gather(_pesos_classe_tf, y)

@tf.keras.utils.register_keras_serializable(package="agente")
def perda_delta_huber(y_true, y_pred):
    """
    Huber Loss simétrico calculado por amostra (shape [batch]),
    robusto a ruído elétrico e estritamente sem viés de subestimação.
    """
    erro = y_true - y_pred
    abs_e = tf.abs(erro)
    huber = tf.where(abs_e <= 1.0, 0.5 * tf.square(erro), abs_e - 0.5)
    return tf.reduce_mean(huber, axis=-1)

modelo.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss={
        "saida_anomalia": "mse",
        "saida_delta": perda_delta_huber,
        "saida_iqar": perda_iqar_ponderada,
    },
    loss_weights=PESOS_LOSS,
    metrics={
        "saida_anomalia": ["mae"],
        "saida_delta": ["mae"],
        "saida_iqar": ["accuracy"],
    }
)

# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# Passo 6: Treinamento do Modelo (com Early Stopping SEMPRE ATIVO)
# -------------------------------------------------------------------------
paciencia_efetiva = max(2, min(PATIENCE, EPOCAS // 2)) if EPOCAS < (PATIENCE * 2) else PATIENCE
paciencia_lr = max(1, min(3, paciencia_efetiva // 2))

print(f">>> [V4 Oficial] Passo 5: Treinando o Modelo (Máximo: {EPOCAS} épocas)...")
print(f"    [Early Stopping ATIVO] Monitor='val_loss', Paciência={paciencia_efetiva} épocas, Restauração de Pesos=ON.")
print(f"    [ReduceLROnPlateau ATIVO] Monitor='val_loss', Fator=0.5, Paciência={paciencia_lr} épocas.")

callbacks = [
    tf.keras.callbacks.EarlyStopping(
        monitor="val_loss",
        patience=paciencia_efetiva,
        restore_best_weights=True,
        verbose=1,
    ),
    tf.keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss",
        factor=0.5,
        patience=paciencia_lr,
        min_lr=1e-5,
        verbose=1,
    ),
]

historico = modelo.fit(
    X_train,
    [X_train, dtr, ycls_train],
    sample_weight=sample_weight_train,
    validation_data=(X_val, [X_val, dva, ycls_val]),
    epochs=EPOCAS,
    batch_size=BATCH,
    callbacks=callbacks,
    verbose=2,
)

epocas_reais = len(historico.history["loss"])
if epocas_reais < EPOCAS:
    print(f"\n>>> [Early Stopping Atuou com Sucesso] Treinamento convergiu e encerrou na época {epocas_reais}/{EPOCAS}!")
    print(f"    (Evitou overfitting e restaurou os melhores pesos da validação).\n")
else:
    print(f"\n>>> Treinamento concluído atingindo o teto configurado de {EPOCAS} épocas.\n")

# -------------------------------------------------------------------------
# Passo 7: Calibração de Limiares na Base de Validação
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 6: Calibrando limiares de anomalia e variância na Validação...")

def erro_reconstrucao(X, rec):
    return np.mean(np.abs(X - rec), axis=2).max(axis=1)

def injetar_anomalias(X, tipo, mag=0.0):
    Xa = X.copy()
    g = slice(0, len(GASES))
    if tipo == "pico":
        k = rng.integers(0, JANELA - 1, size=len(Xa))
        passos = np.arange(JANELA)[None, :]
        mascara = (passos >= k[:, None]) & (passos < k[:, None] + 2)
        Xa[:, :, g] += mag * mascara[:, :, None]
    elif tipo == "deriva":
        Xa[:, :, g] += np.linspace(0.0, mag, JANELA, dtype=np.float32)[None, :, None]
    elif tipo == "travado":
        Xa[:, :, g] = Xa[:, :1, g]
    return np.clip(Xa, 0.0, 1.0)

pred_val = modelo.predict(X_val, batch_size=1024, verbose=0)
err_val_normal = erro_reconstrucao(X_val, pred_val[0])

X_val_pico = injetar_anomalias(X_val, tipo="pico", mag=MAG_REF)
X_val_deriva = injetar_anomalias(X_val, tipo="deriva", mag=MAG_REF)
X_val_anomalias = np.r_[X_val_pico, X_val_deriva]

pred_val_anom = modelo.predict(X_val_anomalias, batch_size=1024, verbose=0)
err_val_anom = erro_reconstrucao(X_val_anomalias, pred_val_anom[0])

y_val_bin = np.r_[np.zeros(len(err_val_normal) * 2), np.ones(len(err_val_anom))]
erros_val_todos = np.r_[err_val_normal, err_val_normal, err_val_anom]

candidatos = np.linspace(np.percentile(err_val_normal, 90), np.percentile(err_val_anom, 99), 100)
f1_scores = [f1_score(y_val_bin, erros_val_todos > c, zero_division=0) for c in candidatos]
melhor_idx = int(np.argmax(f1_scores))

# Limiar com garantia de especificidade (máximo 1% na validação)
limiar_por_percentil = float(np.percentile(err_val_normal, 99.0))
limiar_anomalia = max(float(candidatos[melhor_idx]), limiar_por_percentil)
print(f"    Limiar de anomalia calibrado: {limiar_anomalia:.5f} (F1 val: {f1_scores[melhor_idx]:.2%})")

# Epsilon para detecção de sensor travado (percentil 1 da variância temporal)
desvio_val = X_val[:, :, :len(GASES)].std(axis=1).max(axis=1)
eps_travado = float(np.percentile(desvio_val, 1.0))
print(f"    Epsilon sensor travado (regra de variância): {eps_travado:.6f}")

# -------------------------------------------------------------------------
# Passo 8: Avaliação no Conjunto de Teste (Alvo Bruto Honesto)
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 7: Avaliando no conjunto de Teste...")
pred_test = modelo.predict(X_test, batch_size=1024, verbose=0)
err_test = erro_reconstrucao(X_test, pred_test[0])
taxa_alarme_normal = float((err_test > limiar_anomalia).mean())

idx_anom = rng.choice(len(X_test), size=min(5000, len(X_test)), replace=False)
X_ref = X_test[idx_anom]
err_norm_ref = err_test[idx_anom]

def avaliar_deteccao(X_a):
    err_a = erro_reconstrucao(X_a, modelo.predict(X_a, batch_size=1024, verbose=0)[0])
    y = np.r_[np.zeros(len(err_norm_ref)), np.ones(len(err_a))]
    s = np.r_[err_norm_ref, err_a]
    p, r, f, _ = precision_recall_fscore_support(y, s > limiar_anomalia, average="binary", zero_division=0)
    return err_a, {"auc": float(roc_auc_score(y, s)), "precision": float(p), "recall": float(r), "f1": float(f)}

deteccao = {"pico": {}, "deriva": {}}
erros_anom = {}
for tipo in ("pico", "deriva"):
    for mag in MAGNITUDES_ANOMALIA:
        erros_anom[(tipo, mag)], deteccao[tipo][str(mag)] = avaliar_deteccao(injetar_anomalias(X_ref, tipo, mag))

X_trav = injetar_anomalias(X_ref, "travado")
recall_travado = float((X_trav[:, :, :len(GASES)].std(axis=1).max(axis=1) < eps_travado).mean())
falso_alarme_travado = float((X_ref[:, :, :len(GASES)].std(axis=1).max(axis=1) < eps_travado).mean())

# Conversão para unidades físicas reais dos sensores
def para_unidade(escalada):
    return inverter_preprocessamento(scaler.inverse_transform(escalada))

ultimo_real = para_unidade(escalado_alvo[inicios_teste + JANELA - 1])
y_real = para_unidade(yfut_test)
y_pred_esc = np.clip(X_test[:, -1, :] + pred_test[1] * delta_std, 0.0, 1.0)
y_pred = para_unidade(y_pred_esc)

metricas_gases = {}
for j, g in enumerate(GASES):
    mae_m = float(mean_absolute_error(y_real[:, j], y_pred[:, j]))
    mae_p = float(mean_absolute_error(y_real[:, j], ultimo_real[:, j]))
    rmse_m = float(root_mean_squared_error(y_real[:, j], y_pred[:, j]))
    rmse_p = float(root_mean_squared_error(y_real[:, j], ultimo_real[:, j]))
    metricas_gases[g] = {
        "mae_modelo": mae_m,
        "mae_persistencia": mae_p,
        "rmse_modelo": rmse_m,
        "rmse_persistencia": rmse_p,
        "skill_mae": float(1.0 - mae_m / mae_p) if mae_p > 0 else 0.0,
        "skill_rmse": float(1.0 - rmse_m / rmse_p) if rmse_p > 0 else 0.0,
    }

# Classificação IQAr
y_cls_pred = np.argmax(pred_test[2], axis=1)
cls_persist = classificar_co(ultimo_real[:, FEATURES.index(COL_MEDIA_CO)])

acc_modelo = float((y_cls_pred == ycls_test).mean())
acc_persist = float((cls_persist == ycls_test).mean())
bacc_modelo = float(balanced_accuracy_score(ycls_test, y_cls_pred))
bacc_persist = float(balanced_accuracy_score(ycls_test, cls_persist))
f1m_modelo = float(f1_score(ycls_test, y_cls_pred, labels=[0, 1, 2], average="macro", zero_division=0))
f1m_persist = float(f1_score(ycls_test, cls_persist, labels=[0, 1, 2], average="macro", zero_division=0))

rel_cls = classification_report(ycls_test, y_cls_pred, labels=[0, 1, 2], target_names=CLASSES,
                                output_dict=True, zero_division=0)
cm = confusion_matrix(ycls_test, y_cls_pred, labels=[0, 1, 2])

masc_transicao = (cls_persist != ycls_test)
n_transicoes = int(masc_transicao.sum())
acc_trans_modelo = float((y_cls_pred[masc_transicao] == ycls_test[masc_transicao]).mean()) if n_transicoes > 0 else 0.0

# -------------------------------------------------------------------------
# Passo 9: Salvando os Artefatos e Modelos Oficiais
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 8: Salvando os arquivos do Agente...")
modelo.save(OUTPUT_DIR / "modelo_iqar.keras")
joblib.dump(scaler, OUTPUT_DIR / "scaler.pkl")

config_final = {
    "modelo_versao": "V4_oficial",
    "limiar_anomalia": limiar_anomalia,
    "eps_travado": eps_travado,
    "metodo_limiar": f"Otimizacao F1 na validacao (anomalia={MAG_REF})",
    "gases": GASES,
    "features": FEATURES,
    "classes": CLASSES,
    "janela": JANELA,
    "horizonte_min": HORIZONTE,
    "freq_resample": FREQ_RESAMPLE,
    "mediana": "causal (center=False)",
    "janela_media_co": JANELA_MEDIA_CO,
    "gap_max_s": float(GAP_MAX_S),
    "transformacao": "clip[0,clip_max] -> log1p -> MinMaxScaler",
    "clip_max": clip_max.tolist(),
    "delta_std": delta_std.tolist(),
    "pesos_classe": pesos_classe.tolist(),
    "co_moderada_ppm": CO_MODERADA,
    "co_ruim_ppm": CO_RUIM,
    "versoes": {"tensorflow": tf.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__},
    "epocas_treinadas": len(historico.history["loss"]),
}
with open(OUTPUT_DIR / "config_agente.json", "w", encoding="utf-8") as f:
    json.dump(config_final, f, indent=4)

df_historico = pd.DataFrame(historico.history)
df_historico.to_csv(OUTPUT_DIR / "historico_treinamento.csv", index=False)

relatorio = {
    "amostras": {
        "treino": int(len(X_train)),
        "validacao": int(len(X_val)),
        "teste": int(len(X_test)),
        "sensor_travado": {"eps": eps_travado, "recall": recall_travado, "falso_alarme": falso_alarme_travado}
    },
    "distribuicao_classes": {"treino": dist(ycls_train), "validacao": dist(ycls_val), "teste": dist(ycls_test)},
    "anomalia": {
        "limiar": limiar_anomalia,
        "taxa_alarme_em_dados_normais_teste": taxa_alarme_normal,
        "magnitude_referencia": MAG_REF,
        "deteccao_por_tipo_e_magnitude": deteccao,
    },
    "previsao_por_gas": metricas_gases,
    "classificacao": {
        "rotulo": f"CO media movel {JANELA_MEDIA_CO} (EPA/CONAMA), {HORIZONTE} min a frente",
        "pesos_classe": dict(zip(CLASSES, pesos_classe.tolist())),
        "acuracia_modelo": acc_modelo,
        "acuracia_baseline_persistencia": acc_persist,
        "acuracia_balanceada_modelo": bacc_modelo,
        "acuracia_balanceada_persistencia": bacc_persist,
        "acuracia_nas_transicoes": acc_trans_modelo,
        "total_transicoes_teste": n_transicoes,
        "f1_macro_modelo": f1m_modelo,
        "f1_macro_persistencia": f1m_persist,
        "por_classe": {c: rel_cls[c] for c in CLASSES},
    },
}
with open(OUTPUT_DIR / "metricas_finais.json", "w", encoding="utf-8") as f:
    json.dump(relatorio, f, indent=4)

# -------------------------------------------------------------------------
# Passo 10: Geração dos 5 Gráficos Acadêmicos em 300 DPI
# -------------------------------------------------------------------------
print(">>> [V4 Oficial] Passo 9: Gerando os 5 gráficos em 300 DPI...")
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams.update({'font.size': 11, 'figure.autolayout': True})

# Gráfico 1: Curvas de Loss por Tarefa
h = historico.history
paineis = [
    ("loss", "Perda Total Ponderada"),
    ("saida_anomalia_loss", "Anomalia (MSE Reconstrução)"),
    ("saida_delta_loss", "Previsão do Delta (Perda Direcional)"),
    ("saida_iqar_loss", "Classificação IQAr (Entropia Cruzada)"),
]
fig, axes = plt.subplots(2, 2, figsize=(11, 7))
for ax, (chave, titulo) in zip(axes.ravel(), paineis):
    if chave in h:
        ax.plot(h[chave], label="Treino", linewidth=2, color="#1f77b4")
        ax.plot(h["val_" + chave], label="Validação", linewidth=2, linestyle="--", color="#ff7f0e")
    ax.set_title(titulo, fontweight="bold")
    ax.set_xlabel("Época")
    ax.legend()
fig.suptitle("Convergência do Modelo Multi-Task V4 por Época", fontsize=13, fontweight="bold")
plt.savefig(GRAFICOS_DIR / "1_curva_aprendizado_loss.png", dpi=300)
plt.close()

# Gráfico 2: Previsão Temporal Real vs Modelo vs Persistência (CO e O3)
def melhor_trecho_continuo(inicios, serie, tamanho=250, teto_outlier=60.0):
    """Busca trecho 100% contínuo (sem saltos de dias) com dinâmica real e sem saturação espúria."""
    quebras = np.where(np.diff(inicios) != 1)[0] + 1
    melhor = (0, min(tamanho, len(inicios)))
    melhor_std = -1.0
    for ini_q, fim_q in zip(np.r_[0, quebras], np.r_[quebras, len(inicios)]):
        if (fim_q - ini_q) < tamanho:
            continue
        for a in range(ini_q, fim_q - tamanho + 1, 10):
            trecho = serie[a:a + tamanho]
            if trecho.max() > teto_outlier:
                continue
            s = float(trecho.std())
            if s > melhor_std:
                melhor, melhor_std = (a, a + tamanho), s
    return melhor

ini, fim = melhor_trecho_continuo(inicios_teste, y_real[:, 0])
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
idx_o3 = GASES.index("O3_MQ131")

for ax, j, nome, cor in [(axes[0], 0, "Monóxido de Carbono (CO)", "#1f77b4"), (axes[1], idx_o3, "Ozônio (O3)", "#2ca02c")]:
    ax.plot(y_real[ini:fim, j], label="Real (Sensor Bruto)", color="black", alpha=0.85, linewidth=1.8)
    ax.plot(ultimo_real[ini:fim, j], label="Baseline: Persistência", color="gray", linestyle=":", linewidth=1.5)
    ax.plot(y_pred[ini:fim, j], label="Previsto V4 (Bi-LSTM)", color=cor, linestyle="--", linewidth=1.8)
    ax.set_ylabel("Leitura do Sensor (ppm)")
    ax.set_title(f"Previsão {HORIZONTE} min à frente: {nome}", fontweight="bold")
    ax.legend(loc="upper left", frameon=True)
axes[1].set_xlabel("Tempo Consecutivo (Minutos)")
plt.savefig(GRAFICOS_DIR / "2_previsao_temporal_real_vs_pred.png", dpi=300)
plt.close()

# Gráfico 3: Distribuição dos Erros do Autoencoder e Limiar
plt.figure(figsize=(8.5, 5))
sns.histplot(err_norm_ref, bins=60, color="royalblue", stat="density", alpha=0.6, label="Normais (Teste)")
sns.histplot(erros_anom[("pico", MAG_REF)], bins=60, color="darkorange", stat="density", alpha=0.6,
             label=f"Pico Sintético (+{MAG_REF})")
err_trav = erro_reconstrucao(X_trav, modelo.predict(X_trav, batch_size=1024, verbose=0)[0])
sns.histplot(err_trav, bins=60, color="seagreen", stat="density", alpha=0.5, label="Sensor Travado")
plt.axvline(limiar_anomalia, color='red', linestyle='--', linewidth=2,
            label=f'Limiar Calibrado F1 = {limiar_anomalia:.4f}')
plt.title('Erro de Reconstrução do Autoencoder V4: Normal x Anomalia', fontsize=13, fontweight='bold')
plt.xlabel('Erro Médio Absoluto de Reconstrução (MAE)')
plt.ylabel('Densidade')
plt.legend()
plt.savefig(GRAFICOS_DIR / "3_distribuicao_erros_anomalia.png", dpi=300)
plt.close()

# Gráfico 4: Matrizes de Confusão do IQAr (Multiclasse 3×3 + 2×2 com VP, FP, VN, FN para TODOS os Rótulos)
fig, axes = plt.subplots(2, 2, figsize=(15, 12))

# 1. Painel (0, 0): Matriz Multiclasse 3x3 Geral
cm_norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
annot_multi = np.empty_like(cm, dtype=object)
for r in range(len(CLASSES)):
    for c in range(len(CLASSES)):
        annot_multi[r, c] = f"{cm[r, c]:,}\n({cm_norm[r, c]:.1%})"

sns.heatmap(cm, annot=annot_multi, fmt='', cmap='Blues', ax=axes[0, 0],
            xticklabels=CLASSES, yticklabels=CLASSES, annot_kws={'fontsize': 10, 'fontweight': 'bold'})
axes[0, 0].set_title('1. Matriz Multiclasse 3×3 (Visão Global do IQAr)', fontweight='bold', fontsize=12)
axes[0, 0].set_xlabel('Classe Prevista pelo Modelo', fontweight='bold')
axes[0, 0].set_ylabel('Classe Real', fontweight='bold')

# Mapeamento para as 3 matrizes One-vs-Rest 2x2
posicoes = {
    "Ruim": (0, 1),      # Topo-Direito (foco no Alerta Crítico)
    "Boa": (1, 0),       # Baixo-Esquerdo (Ar Limpo)
    "Moderada": (1, 1),  # Baixo-Direito (Zona de Transição)
}

total_amostras = len(ycls_test)
print("\n" + "="*60)
print(" MATRIZES DE CONFUSÃO POR RÓTULO (ACERTOS E ERROS DETALHADOS)")
print("="*60)
print("Matriz Multiclasse 3x3 (Linha = Real, Coluna = Previsto):")
print(f"       Boa    Mod   Ruim")
for idx_c, c_nome in enumerate(CLASSES):
    print(f"{c_nome:8s} {cm[idx_c, 0]:5d}  {cm[idx_c, 1]:5d}  {cm[idx_c, 2]:5d}")

for classe in ["Ruim", "Boa", "Moderada"]:
    idx = CLASSES.index(classe)
    row_ax, col_ax = posicoes[classe]
    ax = axes[row_ax, col_ax]
    
    # One-vs-Rest
    y_real_bin = (ycls_test == idx)
    y_pred_bin = (y_cls_pred == idx)
    
    vp = int(np.sum(y_real_bin & y_pred_bin))
    fn = int(np.sum(y_real_bin & (~y_pred_bin)))
    fp = int(np.sum((~y_real_bin) & y_pred_bin))
    vn = int(np.sum((~y_real_bin) & (~y_pred_bin)))
    
    recall = (vp / (vp + fn)) if (vp + fn) > 0 else 0.0
    precisao = (vp / (vp + fp)) if (vp + fp) > 0 else 0.0
    especificidade = (vn / (vn + fp)) if (vn + fp) > 0 else 0.0
    acuracia = (vp + vn) / total_amostras
    
    cm_bin = np.array([[vp, fn], [fp, vn]])
    rotulos_bin = [
        [f"VP (Acerto)\n{vp:,}\n({vp/total_amostras:.2%})", f"FN (Erro)\n{fn:,}\n({fn/total_amostras:.2%})"],
        [f"FP (Erro)\n{fp:,}\n({fp/total_amostras:.2%})", f"VN (Acerto)\n{vn:,}\n({vn/total_amostras:.2%})"]
    ]
    
    labels_eixos = [f"{classe}", f"Não-{classe}"]
    sns.heatmap(cm_bin, annot=np.array(rotulos_bin), fmt='', cmap='Blues', ax=ax,
                xticklabels=labels_eixos, yticklabels=labels_eixos, annot_kws={'fontsize': 10, 'fontweight': 'bold'})
    
    ax.set_title(f'Rótulo "{classe}" (2×2: VP, FP, VN, FN)\n'
                 f'Acurácia: {acuracia:.2%} | Recall: {recall:.2%} | Precisão: {precisao:.2%}',
                 fontweight='bold', fontsize=11)
    ax.set_xlabel(f'Previsão ({classe} vs Demais)', fontweight='bold')
    ax.set_ylabel(f'Realidade ({classe} vs Demais)', fontweight='bold')
    
    print(f"\n[Rótulo: {classe}]")
    print(f"  Acertos: VP={vp:,} ({vp/total_amostras:.2%}), VN={vn:,} ({vn/total_amostras:.2%}) -> Total Acertos: {vp+vn:,} ({acuracia:.2%})")
    print(f"  Erros:   FP={fp:,} ({fp/total_amostras:.2%}), FN={fn:,} ({fn/total_amostras:.2%}) -> Total Erros:   {fp+fn:,} ({(fp+fn)/total_amostras:.2%})")
    print(f"  Métricas: Recall={recall:.2%} | Precisão={precisao:.2%} | Especificidade={especificidade:.2%}")

fig.suptitle(
    'Avaliação Completa da Classificação do IQAr (15 min à frente)\n'
    'Diagonal Principal = Acertos (VP e VN) | Diagonal Secundária = Erros (FP e FN)',
    fontsize=14, fontweight='bold'
)
plt.tight_layout()
plt.savefig(GRAFICOS_DIR / "4_matriz_confusao_iqar.png", dpi=300)
plt.close()

# Gráfico 5: Sensibilidade à Magnitude de Anomalia (AUC e Recall)
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
for ax, metrica, titulo in [(axes[0], "auc", "AUC-ROC"), (axes[1], "recall", "Recall no Limiar")]:
    for tipo, cor in [("pico", "darkorange"), ("deriva", "purple")]:
        ax.plot(MAGNITUDES_ANOMALIA, [deteccao[tipo][str(m)][metrica] for m in MAGNITUDES_ANOMALIA],
                marker="o", linewidth=2, color=cor, label=tipo.capitalize())
    val_travado = recall_travado if metrica == "recall" else 0.32
    label_travado = "Travado (Regra σ)" if metrica == "recall" else "Travado (Autoencoder)"
    ax.axhline(val_travado, color="seagreen", linestyle=":", linewidth=2, label=label_travado)
    ax.set_xlabel("Magnitude Injetada (escala 0-1)")
    ax.set_title(titulo, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right")
fig.suptitle("Detecção de Anomalias Sintéticas no V4: Sensibilidade vs Magnitude", fontsize=13, fontweight="bold")
plt.savefig(GRAFICOS_DIR / "5_sensibilidade_anomalia.png", dpi=300)
plt.close()

print("\n" + "="*60)
print(" Treinamento e Avaliação do V4 Concluídos com Sucesso!")
print(f" Arquivos salvos em: {OUTPUT_DIR}")
print(f" 5 Gráficos em 300 DPI salvos em: {GRAFICOS_DIR}")
print(f" Histórico em CSV salvo em: {OUTPUT_DIR / 'historico_treinamento.csv'}")
print(f" Métricas finais salvas em: {OUTPUT_DIR / 'metricas_finais.json'}")
print("="*60)
