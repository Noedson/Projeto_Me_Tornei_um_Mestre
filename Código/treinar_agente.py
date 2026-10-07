from sklearn.metrics import root_mean_squared_error
import json
import joblib
import numpy as numpai
import pandas as panda
from pathlib import Path
import tensorflow as tf
from tensorflow.keras import layers, Model
from sklearn.preprocessing import MinMaxScaler

#Elaboração dos griaficos

import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, mean_absolute_error, root_mean_squared_error

#Passo numero 1: A Configuração

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "event_up.csv"
OUTPUT_DIR = BASE_DIR / "agente"
OUTPUT_DIR.mkdir(exist_ok=True)

JANELA = 12 #12 Passos

GASES = [
    "CO_MQ135",
    "CO2_MQ135",
    "MH4_MQ135",
    "Aceton_MQ135",
    "Alcool_MQ135",
    "Toluen_MQ135",
    "O3_MQ131"
]

print(">>> Passo 1: Lendo e extrarindo dados de 'events_up.csv'...")

#Lê as colunas relevanto do CSV (separador ponto e virgula)

df_raw = panda.read_csv(CSV_PATH, sep = ";", usecols = ['time','object'])

#converte a coluna 'time' para datetime e ordena cronologicamente

df_raw['time'] = panda.to_datetime(df_raw['time'], format = 'ISO8601')
df_raw = df_raw.sort_values('time').reset_index(drop=True)

#Extrai o Json da Colula 'object'

def extrair_gases(texto_json):
    try:
        dados = json.loads(texto_json)
        return [float(dados.get(g, 0.0)) for g in GASES]
    except:
        return [numpai.nan] * len(GASES)

print(">>> Passo 2: Processando leituras dos sensores...")

matriz_gases = [extrair_gases(obj) for obj in df_raw['object']]
df_feature = panda.DataFrame(matriz_gases, columns=GASES)
df_feature = df_feature.ffill().bfill() # Aqui tratamos os valores nulos

# Modificação Numero 1: Filtragem de ruídos espúrios/elétricos dos sensores ---
# O percentil 99.9 preserva 99.9% da dinâmica real e corta picos irreais de até 531 milhões
for gas in GASES:
    teto_aceitavel = df_feature[gas].quantile(0.999)
    df_feature[gas] = df_feature[gas].clip(lower=0.0, upper=teto_aceitavel)

#Criando classes sintéticos para o IQAr para a classificação (cabeça 3)
#0 = boa, 1 = Moderada, 2 = Ruim (baseada no percentil do CO e do Ozônio)

limiar_mod = df_feature['CO_MQ135'].quantile(0.70)
limiar_ruim = df_feature['CO_MQ135'].quantile(0.90)

def classificar_iqar(row):
    if row['CO_MQ135'] > limiar_ruim or row["O3_MQ131"] > 2.0:
        return 2 #Ruim
    elif row['CO_MQ135'] > limiar_mod:
        return 1 # Moderado
    return 0 #Boa

rotulos_classes = df_feature.apply(classificar_iqar, axis= 1).values

#Passo numero 2: Divisão Cronológica (80% treino / 20 Teste)

n_amostras = len(df_feature)
split_ids = int(n_amostras * 0.8)

train_raw =     df_feature.iloc[:split_ids].values
test_raw =      df_feature.iloc[split_ids:].values
train_classes = rotulos_classes[:split_ids]
test_classes =  rotulos_classes[split_ids:]

print(f"total de registros: {n_amostras} | Treino {len(train_raw)} | Teste {len(test_raw)}")

#Passo numero 3: Normalização (fit apenas no treino)

scaler = MinMaxScaler()
train_scaled = scaler.fit_transform(train_raw)
test_scaled = scaler.transform(test_raw)

#Passo numero 4: Criação de Janelas Deslizantes (Sliding Window)

def criar_dataset(dados, classes, janela = 12):
    X, y_rec, y_fore, y_class = [], [], [], []
    for i in range(len(dados) - janela):
        X.append(dados[i:i + janela])
        y_rec.append(dados[i:i + janela])   #Alvo numero 1: Reconstrução
        y_fore.append(dados[i + janela])    #Alvo numero 2: Prever o passo seguinte
        y_class.append(classes[i + janela]) #Alvo numero 3: Classe do passo seguinte
    return numpai.array(X), numpai.array(y_rec), numpai.array(y_fore), numpai.array(y_class)

print(">>> Passo numero 3: Criando tensores de janelas temporais")

X_train, y_rec_train, y_fore_train, y_class_train = criar_dataset(train_scaled, train_classes, JANELA)
X_test, y_rec_test, y_fore_test, y_class_test = criar_dataset(test_scaled, test_classes, JANELA)

#Passo numero 5: Construção da Arquitetura Multi - Task no Keras

print(">>> Passo numero 4: Construindo a rede neural Multi - Task")

entrada = layers.Input(shape=(JANELA, len(GASES)), name="input_sensores")

#Shared Encoder

lstm_shared = layers.Bidirectional(layers.LSTM(64, return_sequences=True))(entrada)
lstm_shared = layers.Dropout(0.2)(lstm_shared)
features_latentes = layers.LSTM(32, return_sequences=False)(lstm_shared)

#Cabeça numero 1 : Detecção de Anomalia

repeat = layers.RepeatVector(JANELA)(features_latentes)
dec_lstm = layers.LSTM(64, return_sequences=True)(repeat)
saida_anomalia = layers.TimeDistributed(layers.Dense(len(GASES)), name="saida_anomalia")(dec_lstm)

#Cabeça numero 2 : Previsão temporal

dense_fore = layers.Dense(32, activation="relu")(features_latentes)
saida_previsao = layers.Dense(len(GASES), activation="sigmoid", name="saida_previsao")(dense_fore)

#Cabeça numero 3: Classificação da Qualidade do Ar (IQAr)

dense_class = layers.Dense(16, activation="relu")(features_latentes)
saida_iqar = layers.Dense(3, activation="softmax", name="saida_iqar")(dense_class)
modelo = Model(
    inputs=entrada,
    outputs=[saida_anomalia, saida_previsao, saida_iqar],
    name="Agente_IQAr_MultiTask"
)
modelo.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss={
        "saida_anomalia": "mse",
        "saida_previsao": "huber",
        "saida_iqar": "sparse_categorical_crossentropy"
    },
    loss_weights={
        "saida_anomalia": 0.3,
        "saida_previsao": 0.5,
        "saida_iqar": 0.2
    },
    metrics={
        "saida_anomalia": ["mae"],
        "saida_previsao": ["mae"],
        "saida_iqar": ["accuracy"]
    }
)

#Passo numero 6: Treinamento
 
print(">>> Passo numero 5: Treinando o Modelo")

early_stop = tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)

#Treinando com amostras representativas para velocidade
# Ajuste 2: Separa 25.000 para treino e 5.000 para validação com diversidade de classes
X_tr, y_rec_tr, y_fore_tr, y_class_tr = X_train[:25000], y_rec_train[:25000], y_fore_train[:25000], y_class_train[:25000]
X_val, y_rec_val, y_fore_val, y_class_val = X_train[25000:30000], y_rec_train[25000:30000], y_fore_train[25000:30000], y_class_train[25000:30000]

historico = modelo.fit(
    X_tr, 
    {
        "saida_anomalia": y_rec_tr,
        "saida_previsao": y_fore_tr,
        "saida_iqar": y_class_tr
    },
    validation_data=(
        X_val,
        {
            "saida_anomalia": y_rec_val,
            "saida_previsao": y_fore_val,
            "saida_iqar": y_class_val
        }
    ),
    epochs=15,
    batch_size=64,
    callbacks=[early_stop]
)

#Passo numero 7: Calibração do Limiar de Anomalia

print(">>> Passo numero 6: Caligrando limiar na base de teste...")

pred_test = modelo.predict(X_test[:5000], verbose=0)
rec_test = pred_test[0]
erros_reconstrucao = numpai.mean(numpai.abs(X_test[:5000] - rec_test), axis=(1, 2))

#Limiar definido com percentil 95 dos erros normais

limiar_anomalia = float(numpai.percentile(erros_reconstrucao, 95))

#Passo numero 8: Salva os Artefatos

print(">>> Passo numero 7: Salvando os arquivos do Agente...")

modelo.save(OUTPUT_DIR / "modelo_iqar.keras")
joblib.dump(scaler, OUTPUT_DIR / "scaler.pkl")
config = {
    "limiar_anomalia": limiar_anomalia,
    "gases": GASES,
    "classes": ["Boa", "Moderada", "Ruim"]
}
with open(OUTPUT_DIR / "config_agente.json", "w") as f:
    json.dump(config, f, indent=4)

GRAFICOS_DIR = OUTPUT_DIR / "graficos"
GRAFICOS_DIR.mkdir(exist_ok=True)
# -------------------------------------------------------------------------
# A. PERSISTÊNCIA DOS DADOS BRUTOS DE TREINO (CSV)
# -------------------------------------------------------------------------
print(">>> Passo numero 8. Persistindo histórico de treino e métricas em CSV...")
df_historico = panda.DataFrame(historico.history)
df_historico.to_csv(OUTPUT_DIR / "historico_treinamento.csv", index=False)
# Configura estilo acadêmico para os gráficos
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams.update({'font.size': 11, 'figure.autolayout': True})
# -------------------------------------------------------------------------
# GRÁFICO 1: Curva de Convergência da Perda Total (Loss vs Val Loss)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 1: Curva de Loss...")
plt.figure(figsize=(8, 5))
plt.plot(historico.history['loss'], label='Perda de Treinamento (Train Loss)', linewidth=2)
plt.plot(historico.history['val_loss'], label='Perda de Validação (Val Loss)', linewidth=2, linestyle='--')
plt.title('Convergência do Modelo Multi-Task por Época', fontsize=13, fontweight='bold')
plt.xlabel('Época')
plt.ylabel('Perda Total (Loss Ponderada)')
plt.legend()
plt.savefig(GRAFICOS_DIR / "1_curva_aprendizado_loss.png", dpi=300)
plt.close()
# -------------------------------------------------------------------------
# GRÁFICO 2: Previsão Temporal - Real vs Previsto (Gases CO e Ozônio)
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 2: Série Temporal Real vs Previsto...")
# Desnormaliza as previsões do conjunto de teste
y_fore_real = scaler.inverse_transform(y_fore_test[:300]) # Primeiros 300 passos
y_fore_pred = scaler.inverse_transform(pred_test[1][:300])
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
# Gás CO (MQ-135) - Índice 0
axes[0].plot(y_fore_real[:, 0], label='CO Real (Sensor)', color='black', alpha=0.8)
axes[0].plot(y_fore_pred[:, 0], label='CO Previsto (LSTM)', color='blue', linestyle='--')
axes[0].set_ylabel('Concentração CO (ppm)')
axes[0].set_title('Previsão Temporal: Monóxido de Carbono (CO)', fontweight='bold')
axes[0].legend()
# Gás Ozônio (MQ-131) - Índice 6
axes[1].plot(y_fore_real[:, 6], label='O3 Real (Sensor)', color='black', alpha=0.8)
axes[1].plot(y_fore_pred[:, 6], label='O3 Previsto (LSTM)', color='green', linestyle='--')
axes[1].set_ylabel('Concentração O3 (ppm)')
axes[1].set_xlabel('Passo de Tempo (Amostras)')
axes[1].set_title('Previsão Temporal: Ozônio (O3)', fontweight='bold')
axes[1].legend()
plt.savefig(GRAFICOS_DIR / "2_previsao_temporal_real_vs_pred.png", dpi=300)
plt.close()
# -------------------------------------------------------------------------
# GRÁFICO 3: Distribuição dos Erros e Limiar de Anomalia
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 3: Distribuição de Erros e Limiar de Anomalia...")
plt.figure(figsize=(8, 5))
sns.histplot(erros_reconstrucao, kde=True, bins=50, color='royalblue', stat="density")
plt.axvline(limiar_anomalia, color='red', linestyle='--', linewidth=2, 
            label=f'Limiar de Anomalia (P95 = {limiar_anomalia:.4f})')
plt.title('Distribuição do Erro de Reconstrução do Autoencoder', fontsize=13, fontweight='bold')
plt.xlabel('Erro Médio Absoluto de Reconstrução (MAE)')
plt.ylabel('Densidade')
plt.legend()
plt.savefig(GRAFICOS_DIR / "3_distribuicao_erros_anomalia.png", dpi=300)
plt.close()
# -------------------------------------------------------------------------
# GRÁFICO 4: Matriz de Confusão da Classificação do IQAr
# -------------------------------------------------------------------------
print(">>> Gerando Gráfico 4: Matriz de Confusão...")
# Modificação numero: Concerto do Grafico da Matriz de Confusão
# 1. Faz a inferência sobre todo o conjunto de teste (onde existem as classes Moderada e Ruim)
pred_test_all = modelo.predict(X_test, verbose=0)
y_class_pred = numpai.argmax(pred_test_all[2], axis=1)
# 2. Especifica labels=[0, 1, 2] para garantir a dimensão 3x3 mesmo se faltar alguma classe
cm = confusion_matrix(y_class_test, y_class_pred, labels=[0, 1, 2])
plt.figure(figsize=(6, 5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
            xticklabels=['Boa', 'Moderada', 'Ruim'], 
            yticklabels=['Boa', 'Moderada', 'Ruim'])
plt.title('Matriz de Confusão - Classificação do IQAr', fontsize=13, fontweight='bold')
plt.xlabel('Classe Prevista pelo Modelo')
plt.ylabel('Classe Real')
plt.savefig(GRAFICOS_DIR / "4_matriz_confusao_iqar.png", dpi=300)
plt.close()
# -------------------------------------------------------------------------
# RELATÓRIO DE MÉTRICAS NUMÉRICAS PARA A DISSERTAÇÃO
# -------------------------------------------------------------------------
mae_co = mean_absolute_error(y_fore_real[:, 0], y_fore_pred[:, 0])
rmse_co = root_mean_squared_error(y_fore_real[:, 0], y_fore_pred[:, 0])
relatorio = {
    "limiar_anomalia_p95": limiar_anomalia,
    "forecasting_mae_co": float(mae_co),
    "forecasting_rmse_co": float(rmse_co),
    "total_amostras_teste": len(y_fore_test)
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
print(f" Limiar de Anomalia calibrado: {limiar_anomalia:.4f}")
print("="*50)