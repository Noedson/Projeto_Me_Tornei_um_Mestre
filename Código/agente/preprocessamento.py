"""
Pré-processamento compartilhado entre o treino (treinar_agente.py) e a
inferência (services.py).

Manter UMA única implementação garante que o agente em produção veja os dados
exatamente como foram vistos no treino (evita "training-serving skew").
"""
import numpy as np
import pandas as pd

JANELA = 30       # 30 minutos de histórico (com agregação de 1 minuto)
HORIZONTE = 15    # Previsão para 15 minutos à frente

GASES = [
    "CO_MQ135",
    "CO2_MQ135",
    "MH4_MQ135",
    "Aceton_MQ135",
    "Alcool_MQ135",
    "Toluen_MQ135",
    "O3_MQ131",
]

# Média móvel temporal do CO (janela de tempo, não de amostras). As faixas da
# EPA/CONAMA abaixo são definidas para a MÉDIA DE 8 h, não para a leitura
# instantânea; por isso o rótulo do IQAr usa esta média, e ela também entra no
# modelo como 8º canal (sem ela, uma janela de 12 leituras ~1 min não teria como
# "enxergar" as últimas 8 h).
JANELA_MEDIA_CO = "8h"
COL_MEDIA_CO = "CO_media_8h"
FEATURES = GASES + [COL_MEDIA_CO]

# Faixas de norma para o CO (ppm), usadas para rotular a classe do IQAr.
#   Boa      : CO <  CO_MODERADA
#   Moderada : CO_MODERADA <= CO < CO_RUIM
#   Ruim     : CO >= CO_RUIM
# Referências: EPA AQI (CO, 8 h: boa <= 4,4 ppm; moderada 4,5-9,4 ppm) e
# CONAMA 491/2018 / OMS (padrão de 9 ppm em 8 h).
# O O3 do MQ131 NÃO é usado na classificação: suas leituras (mediana ~1,0) estão
# muito acima do padrão de 0,07 ppm, indicando sensor não calibrado em ppm.
CO_MODERADA = 4.5
CO_RUIM = 9.5


def classificar_co(co):
    """Classe do IQAr (0=Boa, 1=Moderada, 2=Ruim) a partir do CO em ppm."""
    co = np.asarray(co, dtype=float)
    return np.where(co >= CO_RUIM, 2, np.where(co >= CO_MODERADA, 1, 0)).astype(int)


def preprocessar(matriz, clip_max):
    """
    Aplica, nesta ordem: clip em [0, clip_max] -> log1p.

    O log1p é essencial: os sensores MQ têm cauda extremamente pesada (mediana
    do CO ~7 ppm, picos de centenas de milhões). Sem ele, o MinMaxScaler
    comprime o sinal útil em ~1% da escala e o autoencoder/previsor ficam cegos.

    A normalização final (MinMaxScaler) é aplicada fora, pois o scaler é
    ajustado apenas com dados de treino.
    """
    matriz = np.asarray(matriz, dtype=float)
    matriz = np.clip(matriz, 0.0, np.asarray(clip_max, dtype=float))
    return np.log1p(matriz)


def inverter_preprocessamento(matriz_log):
    """Inverso do log1p (volta para a unidade original do sensor)."""
    return np.expm1(np.asarray(matriz_log, dtype=float))


def media_movel_co(tempos, co, teto_co):
    """
    Média móvel temporal (JANELA_MEDIA_CO, só passado) do CO limitado a
    [0, teto_co]. O teto evita que um único pico espúrio do MQ-135 (centenas de
    milhões) domine a média de 8 h.

    `tempos` deve estar em ordem cronológica. Usado igualmente no treino e na
    inferência (min_periods=1: no início da série usa o que houver).
    """
    serie = pd.Series(
        np.clip(np.asarray(co, dtype=float), 0.0, float(teto_co)),
        index=pd.DatetimeIndex(tempos),
    )
    return serie.rolling(JANELA_MEDIA_CO, min_periods=1).mean().to_numpy()
