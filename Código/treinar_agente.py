import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
import tensorflow as tf
from tensorflow.keras import layers, Model
import sklearn
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import (
    balanced_accuracy_score, classification_report, confusion_matrix, f1_score,
    mean_absolute_error, precision_recall_fscore_support, roc_auc_score,
    root_mean_squared_error,
)

#Elaboração dos graficos

import matplotlib
matplotlib.use("Agg")  # Gera os PNGs sem precisar de janela
import matplotlib.pyplot as plt
import seaborn as sns

from agente.preprocessamento import (
    GASES, FEATURES, COL_MEDIA_CO, JANELA, JANELA_MEDIA_CO, CO_MODERADA, CO_RUIM,
    classificar_co, media_movel_co, preprocessar, inverter_preprocessamento,
)

#Passo numero 1: A Configuração

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "event_up.csv"
OUTPUT_DIR = BASE_DIR / "agente"
OUTPUT_DIR.mkdir(exist_ok=True)
GRAFICOS_DIR = OUTPUT_DIR / "graficos"
GRAFICOS_DIR.mkdir(exist_ok=True)

SEED = 42
tf.keras.utils.set_random_seed(SEED)
rng = np.random.default_rng(SEED)

# Reamostragem para 1 minuto e horizonte preditivo real de 15 minutos
FREQ_RESAMPLE = "1min"
JANELA = 30                # 30 minutos de histórico observado
HORIZONTE = 15             # Prevê o estado daqui a 15 minutos (elimina o viés dos 5 segundos)
STRIDE_TREINO = 1          # Com dados a cada 1 min, não precisa pular amostras
BATCH, EPOCAS = 128, 50
PESOS_LOSS = {"saida_anomalia": 1.0, "saida_delta": 2.0, "saida_iqar": 1.0}
CLASSES = ["Boa", "Moderada", "Ruim"]
PESO_CLASSE_MAX = 10.0
MAGNITUDES_ANOMALIA = [0.05, 0.1, 0.2, 0.3]
MAG_REF = 0.2              # Magnitude de teste mais perceptível

print(">>> Passo 1: Lendo e extraindo dados de 'event_up.csv'...")

# Lê as colunas relevantes do CSV (separador ponto e virgula)
df_raw = pd.read_csv(CSV_PATH, sep=";", usecols=["time", "object"])

# Converte a coluna 'time' para datetime e ordena cronologicamente
df_raw["time"] = pd.to_datetime(df_raw["time"], format="ISO8601", utc=True)
df_raw = df_raw.sort_values("time").reset_index(drop=True)

# Extrai o Json da Coluna 'object'
def extrair_gases(texto_json):
    try:
        dados = json.loads(texto_json)
        return [float(dados[g]) for g in GASES]
    except (ValueError, KeyError, TypeError):
        return [np.nan] * len(GASES)

print(">>> Passo 2: Processando e reamostrando leituras (1 minuto)...")

matriz_gases = [extrair_gases(obj) for obj in df_raw["object"]]
df = pd.DataFrame(matriz_gases, columns=GASES)
df["time"] = df_raw["time"]
df = df.dropna().sort_values("time").set_index("time")

# Reamostra para 1 minuto (média) para filtrar ruído de alta frequência
df_1m = df[GASES].resample(FREQ_RESAMPLE).mean()
# Tolera pequenos buracos de até 3 minutos interpolando linearmente
df = df_1m.interpolate(method="time", limit=3).dropna().reset_index()

# Segmentação para gaps reais maiores que 15 minutos
dt = df["time"].diff().dt.total_seconds()
GAP_MAX_S = 900.0  # 15 minutos
segmento = (dt > GAP_MAX_S).cumsum().to_numpy()

bruto_gases = df[GASES].to_numpy(dtype=float)
n = len(bruto_gases)
print(f"    Total de amostras reamostradas (1 min): {n}")

# Passo 3: Particionamento em Blocos Semanais (Blocked Time Split)
# Garante que eventos sazonais de poluição existam em Treino (70%), Validação (15%) e Teste (15%)
tempo_s = (df["time"] - df["time"].min()).dt.total_seconds().to_numpy()
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

# Teto de outliers calculado SÓ com o treino (P99.9); aplicado depois em val/teste/produção
clip_gases = np.quantile(bruto_gases[masc_treino], 0.999, axis=0)

# 8º canal: média móvel de 8 h do CO (só passado, limitada ao teto do treino).
co_media = media_movel_co(df["time"], bruto_gases[:, 0], clip_gases[0])
bruto = np.column_stack([bruto_gases, co_media])
clip_max = np.r_[clip_gases, clip_gases[0]]

# Pré-processamento (clip -> log1p) e Normalização (fit apenas no treino)
pre = preprocessar(bruto, clip_max)
scaler = MinMaxScaler()
scaler.fit(pre[masc_treino])
escalado = scaler.transform(pre).astype(np.float32)

# Classe do IQAr por norma: média de 8 h do CO
rotulos = classificar_co(co_media)

# Passo 4: Criação de Janelas Deslizantes com Horizonte Futuro
print(f">>> Passo 3: Criando tensores de janelas temporais (Janela={JANELA}min, Horizonte={HORIZONTE}min)...")

total_passos_janela = JANELA + HORIZONTE - 1
todos_inicios = np.arange(0, n - total_passos_janela)
alvos_futuros = todos_inicios + total_passos_janela

# Janela e horizonte devem estar no mesmo segmento contínuo e na mesma partição
validos = (segmento[todos_inicios] == segmento[alvos_futuros]) & (particao[todos_inicios] == particao[alvos_futuros])
todos_inicios = todos_inicios[validos]
alvos_futuros = alvos_futuros[validos]

inicios_treino = todos_inicios[particao[todos_inicios] == "treino"][::STRIDE_TREINO]
inicios_val = todos_inicios[particao[todos_inicios] == "validacao"]
inicios_teste = todos_inicios[particao[todos_inicios] == "teste"]

def montar(inicios):
    idx = inicios[:, None] + np.arange(JANELA)[None, :]
    X = escalado[idx]                                                   # (m, JANELA, 8)
    y_fut = escalado[inicios + JANELA + HORIZONTE - 1]                 # valor em t + HORIZONTE
    y_cls = rotulos[inicios + JANELA + HORIZONTE - 1]                  # classe em t + HORIZONTE
    return X, y_fut, y_cls

X_train, yfut_train, ycls_train = montar(inicios_treino)
X_val, yfut_val, ycls_val = montar(inicios_val)
X_test, yfut_test, ycls_test = montar(inicios_teste)

# Delta padronizado em relação ao último valor observado na janela
delta_std = np.maximum((yfut_train - X_train[:, -1, :]).std(axis=0), 1e-6).astype(np.float32)

def alvo_delta(X, y_fut):
    return ((y_fut - X[:, -1, :]) / delta_std).astype(np.float32)

dtr, dva = alvo_delta(X_train, yfut_train), alvo_delta(X_val, yfut_val)

def dist(y):
    return {CLASSES[i]: int((y == i).sum()) for i in range(3)}

print(f"    Treino {len(X_train)} | Validação {len(X_val)} | Teste {len(X_test)} janelas")
print(f"    Classes treino: {dist(ycls_train)} | val: {dist(ycls_val)} | teste: {dist(ycls_test)}")

# Passo 5: Construção da Arquitetura Multi-Task no Keras
print(">>> Passo 4: Construindo a rede neural Multi-Task...")

entrada = layers.Input(shape=(JANELA, len(FEATURES)), name="input_sensores")

# Shared Encoder
lstm_shared = layers.Bidirectional(layers.LSTM(32, return_sequences=True))(entrada)
lstm_shared = layers.Dropout(0.2)(lstm_shared)
features_latentes = layers.LSTM(16, return_sequences=False)(lstm_shared)

# Cabeça 1: Detecção de Anomalia (gargalo de 8 neurônios)
gargalo = layers.Dense(8, activation="relu", name="gargalo_anomalia")(features_latentes)
repeat = layers.RepeatVector(JANELA)(gargalo)
dec_lstm = layers.LSTM(16, return_sequences=True)(repeat)
saida_anomalia = layers.TimeDistributed(layers.Dense(len(FEATURES)), name="saida_anomalia")(dec_lstm)

# Cabeça 2: Previsão temporal (delta padronizado, saída linear)
dense_fore = layers.Dense(32, activation="relu")(features_latentes)
dense_fore = layers.Dropout(0.1)(dense_fore)
saida_delta = layers.Dense(len(FEATURES), name="saida_delta")(dense_fore)

# Cabeça 3: Classificação da Qualidade do Ar (IQAr)
dense_class = layers.Dense(16, activation="relu")(features_latentes)
saida_iqar = layers.Dense(3, activation="softmax", name="saida_iqar")(dense_class)

modelo = Model(
    inputs=entrada,
    outputs=[saida_anomalia, saida_delta, saida_iqar],
    name="Agente_IQAr_MultiTask"
)

# Peso por classe balanceado
contagem_cls = np.bincount(ycls_train, minlength=3)
pesos_classe = np.where(contagem_cls > 0, len(ycls_train) / (3.0 * np.maximum(contagem_cls, 1)), 1.0)
pesos_classe = np.minimum(pesos_classe, PESO_CLASSE_MAX).astype(np.float32)
print(f"    Pesos por classe: {dict(zip(CLASSES, np.round(pesos_classe, 3).tolist()))}")
_pesos_classe_tf = tf.constant(pesos_classe)

@tf.keras.utils.register_keras_serializable(package="agente")
def perda_iqar_ponderada(y_true, y_pred):
    y = tf.cast(tf.reshape(y_true, [-1]), tf.int32)
    ce = tf.keras.losses.sparse_categorical_crossentropy(y, y_pred)
    return ce * tf.gather(_pesos_classe_tf, y)

modelo.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss={
        "saida_anomalia": "mse",
        "saida_delta": "huber",
        "saida_iqar": perda_iqar_ponderada,
    },
    loss_weights=PESOS_LOSS,
    metrics={
        "saida_anomalia": ["mae"],
        "saida_delta": ["mae"],
        "saida_iqar": ["accuracy"]
    }
)

# Passo 6: Treinamento
print(">>> Passo 5: Treinando o Modelo...")

callbacks = [
    tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True),
    tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=3, min_lr=1e-5),
]

historico = modelo.fit(
    X_train,
    {"saida_anomalia": X_train, "saida_delta": dtr, "saida_iqar": ycls_train},
    validation_data=(
        X_val,
        {"saida_anomalia": X_val, "saida_delta": dva, "saida_iqar": ycls_val}
    ),
    epochs=EPOCAS,
    batch_size=BATCH,
    callbacks=callbacks,
)

# Passo 7: Calibração Ótima do Limiar de Anomalia via F1-Score na Validação
print(">>> Passo 6: Calibrando limiar ótimo na base de VALIDAÇÃO...")

def erro_reconstrucao(X, rec):
    return np.mean(np.abs(X - rec), axis=(1, 2))

# 7.1 Injeção de anomalias sintéticas
def injetar_anomalias(X, tipo, mag=0.0):
    Xa = X.copy()
    g = slice(0, len(GASES))
    if tipo == "pico":                                       # 2 passos consecutivos inflados
        k = rng.integers(0, JANELA - 1, size=len(Xa))
        passos = np.arange(JANELA)[None, :]
        mascara = (passos >= k[:, None]) & (passos < k[:, None] + 2)
        Xa[:, :, g] += mag * mascara[:, :, None]
    elif tipo == "deriva":                                   # rampa lenta (descalibração)
        Xa[:, :, g] += np.linspace(0.0, mag, JANELA, dtype=np.float32)[None, :, None]
    elif tipo == "travado":                                  # primeira leitura repetida
        Xa[:, :, g] = Xa[:, :1, g]
    return np.clip(Xa, 0.0, 1.0)

pred_val = modelo.predict(X_val, batch_size=1024, verbose=0)
err_val_normal = erro_reconstrucao(X_val, pred_val[0])

# Simula anomalia sintética na validação para achar o limiar de melhor trade-off
X_val_sint = injetar_anomalias(X_val, tipo="pico", mag=MAG_REF)
pred_val_sint = modelo.predict(X_val_sint, batch_size=1024, verbose=0)
err_val_sint = erro_reconstrucao(X_val_sint, pred_val_sint[0])

y_val_bin = np.r_[np.zeros(len(err_val_normal)), np.ones(len(err_val_sint))]
erros_val_todos = np.r_[err_val_normal, err_val_sint]

candidatos = np.linspace(np.percentile(err_val_normal, 90), np.percentile(err_val_sint, 99), 100)
f1_scores = [f1_score(y_val_bin, erros_val_todos > c, zero_division=0) for c in candidatos]
melhor_idx = int(np.argmax(f1_scores))
limiar_anomalia = float(candidatos[melhor_idx])
print(f"    Limiar calibrado: {limiar_anomalia:.5f} (F1 esperado na validação: {f1_scores[melhor_idx]:.2%})")

# Passo 8: Avaliação no TESTE
print(">>> Passo 7: Avaliando no conjunto de teste...")

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
erros_anom["travado"], deteccao["travado"] = avaliar_deteccao(injetar_anomalias(X_ref, "travado"))
_ref = deteccao["pico"][str(MAG_REF)]
auc_anom, p_a, r_a = _ref["auc"], _ref["precision"], _ref["recall"]

# 8.2 Previsão: modelo vs baseline de persistência (repetir o último valor), em unidades do sensor
def para_unidade(escalada):
    return inverter_preprocessamento(scaler.inverse_transform(escalada))

ultimo_real = para_unidade(X_test[:, -1, :])
y_real = para_unidade(yfut_test)
y_pred_esc = X_test[:, -1, :] + pred_test[1] * delta_std
y_pred = para_unidade(np.clip(y_pred_esc, 0.0, 1.0))

metricas_gases = {}
for j, g in enumerate(GASES):
    mae_m = float(mean_absolute_error(y_real[:, j], y_pred[:, j]))
    mae_p = float(mean_absolute_error(y_real[:, j], ultimo_real[:, j]))
    metricas_gases[g] = {
        "mae_modelo": mae_m,
        "mae_persistencia": mae_p,
        "rmse_modelo": float(root_mean_squared_error(y_real[:, j], y_pred[:, j])),
        "skill_vs_persistencia": float(1.0 - mae_m / mae_p) if mae_p > 0 else None,
    }

# 8.3 Classificação vs baseline de persistência
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

# Passo 9: Salva os Artefatos
print(">>> Passo 8: Salvando os arquivos do Agente...")

modelo.save(OUTPUT_DIR / "modelo_iqar.keras")
joblib.dump(scaler, OUTPUT_DIR / "scaler.pkl")
config = {
    "limiar_anomalia": limiar_anomalia,
    "metodo_limiar": f"Otimizacao F1 na validacao (anomalia={MAG_REF})",
    "gases": GASES,
    "features": FEATURES,
    "classes": CLASSES,
    "janela": JANELA,
    "horizonte_min": HORIZONTE,
    "freq_resample": FREQ_RESAMPLE,
    "janela_media_co": JANELA_MEDIA_CO,
    "gap_max_s": float(GAP_MAX_S),
    "transformacao": "clip[0,clip_max] -> log1p -> MinMaxScaler",
    "clip_max": clip_max.tolist(),
    "delta_std": delta_std.tolist(),
    "pesos_classe": pesos_classe.tolist(),
    "co_moderada_ppm": CO_MODERADA,
    "co_ruim_ppm": CO_RUIM,
    "versoes": {"tensorflow": tf.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__},
}
with open(OUTPUT_DIR / "config_agente.json", "w") as f:
    json.dump(config, f, indent=4)

# -------------------------------------------------------------------------
# A. PERSISTÊNCIA DOS DADOS BRUTOS DE TREINO (CSV)
# -------------------------------------------------------------------------
print(">>> Passo numero 9. Persistindo histórico de treino e métricas em CSV...")
df_historico = pd.DataFrame(historico.history)
df_historico.to_csv(OUTPUT_DIR / "historico_treinamento.csv", index=False)
# Configura estilo acadêmico para os gráficos
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams.update({'font.size': 11, 'figure.autolayout': True})

# -------------------------------------------------------------------------
# GRÁFICO 1: Curvas de Convergência (total + uma por tarefa, mesma escala treino/val)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 1: Curvas de Loss por tarefa...")
h = historico.history
paineis = [("loss", "Perda total ponderada"), ("saida_anomalia_loss", "Anomalia (MSE)"),
           ("saida_delta_loss", "Previsão do delta (Huber)"), ("saida_iqar_loss", "Classificação IQAr (entropia cruzada)")]
fig, axes = plt.subplots(2, 2, figsize=(11, 7))
for ax, (chave, titulo) in zip(axes.ravel(), paineis):
    if chave in h:
        ax.plot(h[chave], label="Treino", linewidth=2)
        ax.plot(h["val_" + chave], label="Validação", linewidth=2, linestyle="--")
    ax.set_title(titulo, fontweight="bold")
    ax.set_xlabel("Época")
    ax.legend()
fig.suptitle("Convergência do Modelo Multi-Task por Época", fontsize=13, fontweight="bold")
plt.savefig(GRAFICOS_DIR / "1_curva_aprendizado_loss.png", dpi=300)
plt.close()

# -------------------------------------------------------------------------
# GRÁFICO 2: Previsão Temporal - Real vs Modelo vs Persistência (CO e O3)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 2: Série Temporal Real vs Previsto...")
def melhor_trecho(inicios, serie, tamanho=300):
    """Trecho contínuo com maior variação (evita mostrar só um período calmo)."""
    quebras = np.where(np.diff(inicios) != 1)[0] + 1
    melhor, melhor_std = (0, min(tamanho, len(inicios))), -1.0
    for ini, fim in zip(np.r_[0, quebras], np.r_[quebras, len(inicios)]):
        for a in range(ini, fim - tamanho + 1, tamanho):
            s = float(serie[a:a + tamanho].std())
            if s > melhor_std:
                melhor, melhor_std = (a, a + tamanho), s
    return melhor

a, b = melhor_trecho(inicios_teste, y_real[:, 0])
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
for ax, j, nome, cor in [(axes[0], 0, "Monóxido de Carbono (CO)", "blue"), (axes[1], GASES.index("O3_MQ131"), "Ozônio (O3)", "green")]:
    ax.plot(y_real[a:b, j], label="Real (Sensor)", color="black", alpha=0.8)
    ax.plot(ultimo_real[a:b, j], label="Baseline: persistência", color="gray", linestyle=":")
    ax.plot(y_pred[a:b, j], label="Previsto (LSTM)", color=cor, linestyle="--")
    ax.set_ylabel("Leitura do sensor (unid. do firmware)")
    ax.set_title(f"Previsão {HORIZONTE} min à frente: {nome}", fontweight="bold")
    ax.legend()
axes[1].set_xlabel("Passo de Tempo (Minutos)")
plt.savefig(GRAFICOS_DIR / "2_previsao_temporal_real_vs_pred.png", dpi=300)
plt.close()

# -------------------------------------------------------------------------
# GRÁFICO 3: Distribuição dos Erros (normal x anomalias sintéticas) e Limiar
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 3: Distribuição de Erros e Limiar de Anomalia...")
plt.figure(figsize=(8, 5))
sns.histplot(err_norm_ref, bins=60, color="royalblue", stat="density", alpha=0.6, label="Normais (teste)")
sns.histplot(erros_anom[("pico", MAG_REF)], bins=60, color="darkorange", stat="density", alpha=0.6,
             label=f"Pico sintético (+{MAG_REF})")
sns.histplot(erros_anom["travado"], bins=60, color="seagreen", stat="density", alpha=0.5, label="Sensor travado")
plt.axvline(limiar_anomalia, color='red', linestyle='--', linewidth=2,
            label=f'Limiar Calibrado F1 = {limiar_anomalia:.4f}')
plt.title('Erro de Reconstrução do Autoencoder: normal x anomalia', fontsize=13, fontweight='bold')
plt.xlabel('Erro Médio Absoluto de Reconstrução (MAE)')
plt.ylabel('Densidade')
plt.legend()
plt.savefig(GRAFICOS_DIR / "3_distribuicao_erros_anomalia.png", dpi=300)
plt.close()

# -------------------------------------------------------------------------
# GRÁFICO 5: Sensibilidade da detecção à magnitude da anomalia (AUC e recall)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 5: Sensibilidade à magnitude da anomalia...")
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
for ax, metrica, titulo in [(axes[0], "auc", "AUC-ROC"), (axes[1], "recall", "Recall no limiar")]:
    for tipo, cor in [("pico", "darkorange"), ("deriva", "purple")]:
        ax.plot(MAGNITUDES_ANOMALIA, [deteccao[tipo][str(m)][metrica] for m in MAGNITUDES_ANOMALIA],
                marker="o", color=cor, label=tipo.capitalize())
    ax.axhline(deteccao["travado"][metrica], color="seagreen", linestyle=":", label="Travado")
    ax.set_xlabel("Magnitude injetada (escala normalizada 0-1)")
    ax.set_title(titulo, fontweight="bold")
    ax.set_ylim(0, 1.02)
    ax.legend()
fig.suptitle("Detecção de anomalias sintéticas x magnitude", fontsize=13, fontweight="bold")
plt.savefig(GRAFICOS_DIR / "5_sensibilidade_anomalia.png", dpi=300)
plt.close()

# -------------------------------------------------------------------------
# GRÁFICO 4: Matriz de Confusão (contagem e normalizada por linha = recall)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 4: Matriz de Confusão...")
cm_norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[0], xticklabels=CLASSES, yticklabels=CLASSES)
axes[0].set_title('Contagem', fontweight='bold')
sns.heatmap(cm_norm, annot=True, fmt='.2f', cmap='Blues', vmin=0, vmax=1, ax=axes[1], xticklabels=CLASSES, yticklabels=CLASSES)
axes[1].set_title('Normalizada por classe real (recall)', fontweight='bold')
for ax in axes:
    ax.set_xlabel('Classe Prevista pelo Modelo')
    ax.set_ylabel('Classe Real')
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
fig.suptitle('Matriz de Confusão - Classificação do IQAr (próximo passo)', fontsize=13, fontweight='bold')
plt.savefig(GRAFICOS_DIR / "4_matriz_confusao_iqar.png", dpi=300)
plt.close()

# -------------------------------------------------------------------------
# RELATÓRIO DE MÉTRICAS NUMÉRICAS PARA A DISSERTAÇÃO
# -------------------------------------------------------------------------
relatorio = {
    "amostras": {"treino": int(len(X_train)), "validacao": int(len(X_val)), "teste": int(len(X_test))},
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
        "f1_macro_modelo": f1m_modelo,
        "f1_macro_persistencia": f1m_persist,
        "por_classe": {c: rel_cls[c] for c in CLASSES},
    },
}
with open(OUTPUT_DIR / "metricas_finais.json", "w") as f:
    json.dump(relatorio, f, indent=4)

print("\n" + "="*50)
print(f" Gráficos em 300 DPI salvos em: {GRAFICOS_DIR}")
print(f" Histórico em CSV salvo em: {OUTPUT_DIR / 'historico_treinamento.csv'}")
print("="*50)

print("\n" + "="*50)
print(f" Treinamento concluído com sucesso!")
print(f" Arquivos salvos em: {OUTPUT_DIR}")
print(f" Limiar de Anomalia calibrado (F1): {limiar_anomalia:.5f} | alarme em normais: {taxa_alarme_normal:.2%}")
print(f" Anomalias sintéticas (pico +{MAG_REF}) -> AUC {auc_anom:.3f} | precision {p_a:.3f} | recall {r_a:.3f}")
print(f" CO: MAE modelo {metricas_gases['CO_MQ135']['mae_modelo']:.3f} vs persistência {metricas_gases['CO_MQ135']['mae_persistencia']:.3f}")
print(f" IQAr: F1-macro modelo {f1m_modelo:.3f} vs persistência {f1m_persist:.3f} | "
      f"acurácia bal. {bacc_modelo:.3f} vs {bacc_persist:.3f} | recall Ruim {rel_cls['Ruim']['recall']:.3f}")
print("="*50)