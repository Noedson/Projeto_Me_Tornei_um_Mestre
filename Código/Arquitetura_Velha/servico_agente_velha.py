"""
Serviço HTTP do Agente Inteligente Multi-Task (V4) para a Arquitetura Velha.
Utiliza exatamente os mesmos artefatos (modelo_iqar.keras, scaler.pkl,
config_agente.json e preprocessamento.py) da Arquitetura Nova para garantir
comparação científica 100% justa entre as duas arquiteturas.
"""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

# Permite importar o pacote 'agente' montado em /app/agente
APP_DIR = Path("/app")
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from agente.preprocessamento import GASES, JANELA, preprocessar, media_movel_co, DinamicaTemporal  # noqa: E402

AGENTE_DIR = APP_DIR / "agente"
N_JANELAS_CONFIRMACAO = 3
MIN_JANELAS_ANOMALAS = 2


class AgenteVelhaEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self.model = tf.keras.models.load_model(AGENTE_DIR / "modelo_iqar.keras", compile=False)
        self.scaler = joblib.load(AGENTE_DIR / "scaler.pkl")
        with open(AGENTE_DIR / "config_agente.json", "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.limiar = self.config["limiar_anomalia"]
        self.eps_travado = self.config.get("eps_travado", 0.0015)
        self.classes = self.config.get("classes", ["Boa", "Moderada", "Ruim"])
        self.clip_max = np.asarray(self.config["clip_max"], dtype=float)
        self.delta_std = np.asarray(self.config["delta_std"], dtype=np.float32)
        self.gap_max_s = self.config.get("gap_max_s", 900.0)
        self.cooldown_minutos = 15

        # Histórico em memória por sala/sensor (até 1000 leituras ~ 8h+)
        self.historico = defaultdict(lambda: deque(maxlen=1000))
        self.ultimo_alerta = {}

        # Compila o grafo estático C++ do TensorFlow + Warm-up (~5650ms -> ~31ms)
        self._inferir_grafo = tf.function(
            lambda x: self.model(x, training=False),
            input_signature=[tf.TensorSpec(shape=[None, JANELA, 8], dtype=tf.float32)],
        )
        self._inferir_grafo(tf.zeros((N_JANELAS_CONFIRMACAO, JANELA, 8), dtype=tf.float32))
        print(">>> [Agente IA - Arquitetura Velha] Modelo Multi-Task V4 e Grafo Compilado carregados com sucesso!")

    def _normalizar(self, matriz):
        return self.scaler.transform(preprocessar(matriz, self.clip_max)).astype(np.float32)

    def avaliar(self, room: str, payload_gases: dict, timestamp_str: str | None = None):
        t0 = time.perf_counter()
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        leitura = {
            "timestamp": ts,
            "co_mq135": float(payload_gases.get("CO_MQ135", 0.0)),
            "co2_mq135": float(payload_gases.get("CO2_MQ135", 0.0)),
            "mh4_mq135": float(payload_gases.get("MH4_MQ135", 0.0)),
            "aceton_mq135": float(payload_gases.get("Aceton_MQ135", 0.0)),
            "alcool_mq135": float(payload_gases.get("Alcool_MQ135", 0.0)),
            "toluen_mq135": float(payload_gases.get("Toluen_MQ135", 0.0)),
            "o3_mq131": float(payload_gases.get("O3_MQ131", 0.0)),
        }

        with self._lock:
            hist = self.historico[room]
            hist.append(leitura)
            minimo = JANELA + N_JANELAS_CONFIRMACAO - 1
            if len(hist) < minimo:
                lat_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "pronto": False,
                    "amostras_atuais": len(hist),
                    "amostras_necessarias": minimo,
                    "latencia_agente_ms": round(lat_ms, 3),
                }

            todas = list(hist)
            usadas = todas[-minimo:]

        # Modo Teste é controlado EXCLUSIVAMENTE pela flag explícita APP_TESTE=1
        modo_teste = os.environ.get("APP_TESTE", "0") == "1"

        if modo_teste:
            tempos = [r["timestamp"] for r in usadas]
            dts = [(tempos[i] - tempos[i - 1]).total_seconds() for i in range(1, len(tempos))]
            if any(dt > self.gap_max_s for dt in dts):
                lat_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "pronto": False,
                    "motivo": "gap_temporal_excedido",
                    "latencia_agente_ms": round(lat_ms, 3),
                }
            ultimo_ts = tempos[-1]
            co_janela = [r["co_mq135"] for r in usadas]
            media_co_usadas = media_movel_co(tempos, co_janela, self.clip_max[0])
            matriz_gases = np.array([[
                r["co_mq135"], r["co2_mq135"], r["mh4_mq135"], r["aceton_mq135"],
                r["alcool_mq135"], r["toluen_mq135"], r["o3_mq131"]
            ] for r in usadas], dtype=float)
        else:
            ultimo_ts = todas[-1]["timestamp"]
            oito_horas_atras = ultimo_ts - timedelta(hours=8)
            leituras_8h = [r for r in todas if oito_horas_atras <= r["timestamp"] <= ultimo_ts]
            df_8h = pd.DataFrame([
                {
                    "timestamp": r["timestamp"],
                    "CO_MQ135": r["co_mq135"],
                    "CO2_MQ135": r["co2_mq135"],
                    "MH4_MQ135": r["mh4_mq135"],
                    "Aceton_MQ135": r["aceton_mq135"],
                    "Alcool_MQ135": r["alcool_mq135"],
                    "Toluen_MQ135": r["toluen_mq135"],
                    "O3_MQ131": r["o3_mq131"],
                }
                for r in leituras_8h
            ])
            df_8h["timestamp"] = pd.to_datetime(df_8h["timestamp"], utc=True)
            df_8h = df_8h.set_index("timestamp")
            df_1m = df_8h[GASES].resample("1min").mean().dropna()
            if len(df_1m) < minimo:
                lat_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "pronto": False,
                    "amostras_atuais": len(df_1m),
                    "amostras_necessarias": minimo,
                    "latencia_agente_ms": round(lat_ms, 3),
                }
            df_usadas = df_1m.iloc[-minimo:]
            tempos_1m = df_usadas.index.to_pydatetime().tolist()
            dts = [(tempos_1m[i] - tempos_1m[i - 1]).total_seconds() for i in range(1, len(tempos_1m))]
            if any(dt > self.gap_max_s for dt in dts):
                lat_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "pronto": False,
                    "motivo": "gap_temporal_excedido",
                    "latencia_agente_ms": round(lat_ms, 3),
                }
            media_co_total = media_movel_co(df_1m.index, df_1m["CO_MQ135"].to_numpy(), self.clip_max[0])
            media_co_usadas = media_co_total[-minimo:]
            matriz_gases = df_usadas[GASES].to_numpy(dtype=float)

        matriz = np.column_stack([matriz_gases, media_co_usadas])
        escalada = self._normalizar(matriz)
        n_janelas = len(escalada) - JANELA + 1
        lote = np.stack([escalada[i:i + JANELA] for i in range(n_janelas)])

        with self._lock:
            rec_t, delta_t, class_t = self._inferir_grafo(tf.constant(lote, dtype=tf.float32))
            rec_out, delta_out, class_out = rec_t.numpy(), delta_t.numpy(), class_t.numpy()

        erros = np.mean(np.abs(lote - rec_out), axis=2).max(axis=1)
        n_acima = int((erros > self.limiar).sum())
        anomalia_reconstrucao = n_acima >= min(MIN_JANELAS_ANOMALAS, n_janelas)
        erro_atual = float(erros[-1])

        desvio_recente = lote[-1, :, :7].std(axis=0)
        esta_travado = bool(desvio_recente.max() < self.eps_travado)
        is_anomalia = anomalia_reconstrucao or esta_travado

        previsto_esc = np.clip(lote[-1, -1, :] + delta_out[-1] * self.delta_std, 0.0, 1.0)
        valores_previstos = np.expm1(self.scaler.inverse_transform(previsto_esc[None, :]))[0]
        probs = class_out[-1]
        classe_idx = int(np.argmax(probs))
        nome_classe = self.classes[classe_idx]

        alerta = None
        tipo_alerta = None
        mensagem = ""

        if is_anomalia:
            tipo_alerta = "ANOMALIA"
            if esta_travado:
                mensagem = "Anomalia detectada: sensor travado (leituras sem variação temporal detectável)!"
            else:
                mensagem = (
                    f"Anomalia detectada nos sensores! Erro: {erro_atual:.4f} "
                    f"(Limiar: {self.limiar:.4f}; {n_acima}/{n_janelas} janelas acima)"
                )
        elif classe_idx == 2:
            tipo_alerta = "PREVISAO_CRITICA"
            mensagem = (
                f"Alerta Preditivo (15 min à frente): Risco iminente de qualidade do ar 'Ruim' "
                f"(prob. {probs[2]:.0%}). Projeção futura de CO: {valores_previstos[0]:.2f} ppm"
            )

        if tipo_alerta:
            chave_cd = (room, tipo_alerta)
            ult_alerta = self.ultimo_alerta.get(chave_cd)
            if not ult_alerta or (ultimo_ts - ult_alerta) >= timedelta(minutes=self.cooldown_minutos):
                self.ultimo_alerta[chave_cd] = ultimo_ts
                alerta = {"tipo": tipo_alerta, "mensagem": mensagem}

        lat_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "pronto": True,
            "anomalia": is_anomalia,
            "erro_reconstrucao": erro_atual,
            "classe": nome_classe,
            "probabilidades": {c: float(p) for c, p in zip(self.classes, probs)},
            "previsao": {g: float(v) for g, v in zip(self.config["features"], valores_previstos)},
            "alerta": alerta,
            "latencia_agente_ms": round(lat_ms, 3),
        }


ENGINE = AgenteVelhaEngine()


class AgenteHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/avaliar":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8"))
            room = body.get("room", "sensor_001-room:001")
            gases = body.get("gases", {})
            timestamp_str = body.get("timestamp")

            resultado = ENGINE.avaliar(room, gases, timestamp_str)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resultado).encode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AgenteHandler)
    print(f">>> [Agente IA - Arquitetura Velha] Escutando em http://0.0.0.0:{port}/avaliar ...")
    server.serve_forever()

