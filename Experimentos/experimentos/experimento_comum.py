"""
Pipeline de dados + protocolo de avaliação COMPARTILHADOS entre:
  - treinar_agente_v4.py  (treina a V4)
  - comparar_v3_v4.py     (avalia V3 e V4 sob o mesmo protocolo)

Protocolo honesto:
  * ENTRADA do modelo: série de 1 min com mediana móvel de 3 passos
      - V3: center=True  (usa o minuto futuro -> vazamento)
      - V4: center=False (causal, reproduzível em tempo real)
  * ALVO, PERSISTÊNCIA e RÓTULOS: SEMPRE a série bruta de 1 min (sem mediana).
    Assim nenhuma versão "ganha" por ser avaliada contra um alvo suavizado.
  * Mesmas linhas, segmentos, partições e janelas para as duas versões.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import (
    balanced_accuracy_score, f1_score, mean_absolute_error, roc_auc_score,
    precision_recall_fscore_support, root_mean_squared_error,
)

from agente.preprocessamento import (
    GASES, classificar_co, media_movel_co, preprocessar, inverter_preprocessamento,
)

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "event_up.csv"
JANELA, HORIZONTE = 30, 15
GAP_MAX_S = 900.0
CLASSES = ["Boa", "Moderada", "Ruim"]
SEED = 42


# ---------------------------------------------------------------------------
# Camada de dinâmica temporal (substitui as 3 Lambdas da V3: serializável e
# carregável no Keras 3 sem safe_mode=False)
# ---------------------------------------------------------------------------
@tf.keras.utils.register_keras_serializable(package="agente")
class DinamicaTemporal(layers.Layer):
    """Concatena tendência (t - t-4), velocidade (t - t-1) e aceleração."""

    def call(self, x):
        t = x[:, -1, :]
        tendencia = t - x[:, -5, :]
        velocidade = t - x[:, -2, :]
        aceleracao = (t - x[:, -3, :]) - (x[:, -3, :] - x[:, -5, :])
        return tf.concat([tendencia, velocidade, aceleracao], axis=-1)


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def _extrair(texto):
    try:
        d = json.loads(texto)
        return [float(d[g]) for g in GASES]
    except (ValueError, KeyError, TypeError):
        return [np.nan] * len(GASES)


def carregar_serie_1min():
    """Série bruta reamostrada em 1 min (média) com interpolação de até 3 min."""
    df_raw = pd.read_csv(CSV_PATH, sep=";", usecols=["time", "object"])
    df_raw["time"] = pd.to_datetime(df_raw["time"], format="ISO8601", utc=True)
    df = pd.DataFrame([_extrair(o) for o in df_raw["object"]], columns=GASES)
    df["time"] = df_raw["time"]
    df = df.dropna().sort_values("time").set_index("time")
    return df[GASES].resample("1min").mean().interpolate(method="time", limit=3)


def preparar_dados(center, scaler=None, clip_max=None, serie=None):
    serie = carregar_serie_1min() if serie is None else serie
    filtrada = serie.rolling(window=3, min_periods=1, center=center).median()

    manter = serie.notna().all(axis=1).to_numpy()
    tempos = serie.index[manter]
    bruto = serie.to_numpy(dtype=float)[manter]
    filt = filtrada.to_numpy(dtype=float)[manter]
    n = len(bruto)

    dt = pd.Series(tempos).diff().dt.total_seconds().to_numpy()
    segmento = np.cumsum(np.nan_to_num(dt) > GAP_MAX_S)

    tempo_s = np.asarray((tempos - tempos[0]).total_seconds())
    bloco_id = (tempo_s // (7 * 86400)).astype(int)
    particao = np.full(n, "treino", dtype=object)
    for b in np.unique(bloco_id):
        idx_b = np.where(bloco_id == b)[0]
        nb = len(idx_b)
        if nb < (JANELA + HORIZONTE + 10):
            continue
        particao[idx_b[int(nb * 0.70):int(nb * 0.85)]] = "validacao"
        particao[idx_b[int(nb * 0.85):]] = "teste"
    masc_treino = particao == "treino"

    if clip_max is None:
        clip_g = np.quantile(filt[masc_treino], 0.995, axis=0)
        clip_max = np.r_[clip_g, clip_g[0]]
    clip_max = np.asarray(clip_max, dtype=float)

    co_media_in = media_movel_co(tempos, filt[:, 0], clip_max[0])
    co_media_bruta = media_movel_co(tempos, bruto[:, 0], clip_max[0])
    pre_in = preprocessar(np.column_stack([filt, co_media_in]), clip_max)
    pre_alvo = preprocessar(np.column_stack([bruto, co_media_bruta]), clip_max)

    if scaler is None:
        scaler = MinMaxScaler().fit(pre_in[masc_treino])
    esc_in = scaler.transform(pre_in).astype(np.float32)
    esc_alvo = scaler.transform(pre_alvo).astype(np.float32)
    rotulos = classificar_co(co_media_bruta)

    total = JANELA + HORIZONTE - 1
    inicios = np.arange(0, n - total)
    fut = inicios + total
    ok = (segmento[inicios] == segmento[fut]) & (particao[inicios] == particao[fut])
    inicios = inicios[ok]

    def montar(ini):
        idx = ini[:, None] + np.arange(JANELA)[None, :]
        t_fut, t_now = ini + total, ini + JANELA - 1
        return {
            "X": esc_in[idx],
            "y_fut": esc_alvo[t_fut],      # alvo BRUTO em t+15
            "ultimo": esc_alvo[t_now],     # último valor BRUTO observado (persistência)
            "y_cls": rotulos[t_fut],
            "y_cls_atual": rotulos[t_now],
        }

    dados = {p: montar(inicios[particao[inicios] == p]) for p in ("treino", "validacao", "teste")}
    dados["scaler"], dados["clip_max"] = scaler, clip_max
    return dados


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------
def para_unidade(esc, scaler):
    return inverter_preprocessamento(scaler.inverse_transform(esc))


def aplicar_gate(probs, cls_atual, tau):
    """Mantém a classe atual (persistência) a menos que o modelo tenha confiança > tau."""
    return np.where(probs.max(axis=1) > tau, probs.argmax(axis=1), cls_atual)


def escolher_tau(probs, cls_atual, y_true):
    grade = np.r_[np.linspace(0.50, 0.99, 50), 0.995, 0.999, 1.01]
    f1s = [f1_score(y_true, aplicar_gate(probs, cls_atual, t), labels=[0, 1, 2],
                    average="macro", zero_division=0) for t in grade]
    return float(grade[int(np.argmax(f1s))])


def metricas_classificacao(y_pred, y_true, cls_atual):
    trans = cls_atual != y_true
    return {
        "acuracia": float((y_pred == y_true).mean()),
        "acuracia_balanceada": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, labels=[0, 1, 2], average="macro", zero_division=0)),
        "n_transicoes": int(trans.sum()),
        "acertos_transicoes": int((y_pred[trans] == y_true[trans]).sum()),
        "mudancas_espurias": int(((y_pred != cls_atual) & ~trans).sum()),
    }


def metricas_previsao(y_pred_esc, d, scaler):
    y_real = para_unidade(d["y_fut"], scaler)
    y_pers = para_unidade(d["ultimo"], scaler)
    y_pred = para_unidade(np.clip(y_pred_esc, 0.0, 1.0), scaler)
    out = {}
    for j, g in enumerate(GASES):
        mae_m = float(mean_absolute_error(y_real[:, j], y_pred[:, j]))
        mae_p = float(mean_absolute_error(y_real[:, j], y_pers[:, j]))
        rmse_m = float(root_mean_squared_error(y_real[:, j], y_pred[:, j]))
        rmse_p = float(root_mean_squared_error(y_real[:, j], y_pers[:, j]))
        out[g] = {"mae_modelo": mae_m, "mae_persistencia": mae_p,
                  "rmse_modelo": rmse_m, "rmse_persistencia": rmse_p,
                  "skill_mae": 1 - mae_m / mae_p if mae_p > 0 else None,
                  "skill_rmse": 1 - rmse_m / rmse_p if rmse_p > 0 else None}
    return out


def _erro_rec(X, rec):
    return np.mean(np.abs(X - rec), axis=2).max(axis=1)


def _injetar(X, tipo, mag, rng):
    Xa = X.copy()
    g = slice(0, len(GASES))
    if tipo == "pico":
        k = rng.integers(0, JANELA - 1, size=len(Xa))
        p = np.arange(JANELA)[None, :]
        Xa[:, :, g] += mag * ((p >= k[:, None]) & (p < k[:, None] + 2))[:, :, None]
    elif tipo == "deriva":
        Xa[:, :, g] += np.linspace(0.0, mag, JANELA, dtype=np.float32)[None, :, None]
    return np.clip(Xa, 0.0, 1.0)


def avaliar_anomalia(modelo, dv, dt):
    rng = np.random.default_rng(SEED)
    rec = lambda X: modelo.predict(X, batch_size=1024, verbose=0)[0]
    Xv = dv["X"]
    err_v = _erro_rec(Xv, rec(Xv))
    Xa = np.r_[_injetar(Xv, "pico", 0.2, rng), _injetar(Xv, "deriva", 0.2, rng)]
    err_a = _erro_rec(Xa, rec(Xa))
    y = np.r_[np.zeros(2 * len(err_v)), np.ones(len(err_a))]
    s = np.r_[err_v, err_v, err_a]
    cand = np.linspace(np.percentile(err_v, 90), np.percentile(err_a, 99), 100)
    f1s = [f1_score(y, s > c, zero_division=0) for c in cand]
    limiar = max(float(cand[int(np.argmax(f1s))]), float(np.percentile(err_v, 99)))

    Xt = dt["X"]
    err_t = _erro_rec(Xt, rec(Xt))
    idx = rng.choice(len(Xt), size=min(5000, len(Xt)), replace=False)
    Xr, er = Xt[idx], err_t[idx]
    res = {"limiar": limiar,
           "alarme_validacao": float((err_v > limiar).mean()),
           "alarme_teste": float((err_t > limiar).mean())}
    for tipo in ("pico", "deriva"):
        for mag in (0.1, 0.2, 0.3):
            Xi = _injetar(Xr, tipo, mag, rng)
            ea = _erro_rec(Xi, rec(Xi))
            yy = np.r_[np.zeros(len(er)), np.ones(len(ea))]
            ss = np.r_[er, ea]
            _, r, _, _ = precision_recall_fscore_support(yy, ss > limiar, average="binary", zero_division=0)
            res[f"{tipo}_{mag}"] = {"auc": float(roc_auc_score(yy, ss)), "recall": float(r)}
    return res


def avaliar_modelo(modelo, dados, delta_std):
    dv, dt, scaler = dados["validacao"], dados["teste"], dados["scaler"]
    pv = modelo.predict(dv["X"], batch_size=1024, verbose=0)
    pt = modelo.predict(dt["X"], batch_size=1024, verbose=0)
    tau = escolher_tau(pv[2], dv["y_cls_atual"], dv["y_cls"])
    cls_gate = aplicar_gate(pt[2], dt["y_cls_atual"], tau)
    return {
        "previsao": metricas_previsao(dt["X"][:, -1, :] + pt[1] * delta_std, dt, scaler),
        "classificacao": {
            "persistencia": metricas_classificacao(dt["y_cls_atual"], dt["y_cls"], dt["y_cls_atual"]),
            "modelo": metricas_classificacao(pt[2].argmax(axis=1), dt["y_cls"], dt["y_cls_atual"]),
            "modelo_gate": {**metricas_classificacao(cls_gate, dt["y_cls"], dt["y_cls_atual"]), "tau": tau},
        },
        "anomalia": avaliar_anomalia(modelo, dv, dt),
    }
