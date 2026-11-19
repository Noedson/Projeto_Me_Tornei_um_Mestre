import json
import os
import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from pathlib import Path
import threading
from datetime import timedelta

from .preprocessamento import GASES, JANELA, preprocessar, media_movel_co, DinamicaTemporal

BASE_DIR = Path(__file__).resolve().parent

# Quantas janelas consecutivas mais recentes são avaliadas e quantas precisam
# estar acima do limiar para confirmar a anomalia (evita alarme por 1 leitura ruidosa).
N_JANELAS_CONFIRMACAO = 3
MIN_JANELAS_ANOMALAS = 2


class AirQualifyService:
    """
    Agente Inteligente Multi-Task:
    Carrega o modelo treinado uma única vez (Singleton thread-safe) e avalia:
    1. Detecção de Anomalias (Erro de Reconstrução, confirmada em janelas consecutivas)
    2. Previsão Temporal Futura (Forecasting dos gases, 15 minutos à frente)
    3. Classificação do Nível da Qualidade do Ar (IQAr, 15 minutos à frente)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AirQualifyService, cls).__new__(cls)
                # 1. Carrega o modelo (compile=False para inferência rápida sem precisar recompilar losses), normalizador e configs
                cls._instance.model = tf.keras.models.load_model(BASE_DIR / 'modelo_iqar.keras', compile=False)
                cls._instance.scaler = joblib.load(BASE_DIR / 'scaler.pkl')

                with open(BASE_DIR / 'config_agente.json', 'r') as f:
                    cls._instance.config = json.load(f)

                cfg = cls._instance.config
                cls._instance.limiar = cfg["limiar_anomalia"]
                cls._instance.eps_travado = cfg.get("eps_travado", 0.0015)
                cls._instance.classes = cfg.get("classes", ["Boa", "Moderada", "Ruim"])
                cls._instance.clip_max = np.asarray(cfg["clip_max"], dtype=float)
                cls._instance.delta_std = np.asarray(cfg["delta_std"], dtype=np.float32)
                cls._instance.gap_max_s = cfg.get("gap_max_s", 900.0)
                cls._instance.cooldown_minutos = 15
                cls._instance._modelo_mtime = (BASE_DIR / 'modelo_iqar.keras').stat().st_mtime

                # Compila o grafo estático C++ do TensorFlow (evita loop Python Eager nos 30 passos da Bi-LSTM: ~5650ms -> ~31ms)
                cls._instance._inferir_grafo = tf.function(
                    lambda x: cls._instance.model(x, training=False),
                    input_signature=[tf.TensorSpec(shape=[None, JANELA, 8], dtype=tf.float32)],
                )
                # Warm-up (pré-compila o grafo no carregamento do Singleton para a 1ª requisição já ser rápida)
                cls._instance._inferir_grafo(tf.zeros((N_JANELAS_CONFIRMACAO, JANELA, 8), dtype=tf.float32))
                print(">>> [Agente Inteligente] Modelo Multi-Task Carregado e Grafo Compilado com Sucesso!")
        return cls._instance

    @classmethod
    def recarregar_modelo(cls):
        """
        Recarrega o modelo e o scaler a quente (Zero Downtime).
        Carrega primeiro em variáveis temporárias e troca o ponteiro com thread-lock.
        """
        with cls._lock:
            if cls._instance is not None:
                print(">>> [Agente] Iniciando Hot-Reloading do Modelo...")
                try:
                    # Passo 1: Carrega em variáveis temporárias (se falhar, não afeta o que está no ar)
                    novo_modelo = tf.keras.models.load_model(BASE_DIR / 'modelo_iqar.keras', compile=False)
                    novo_scaler = joblib.load(BASE_DIR / 'scaler.pkl')

                    with open(BASE_DIR / 'config_agente.json', 'r') as f:
                        nova_config = json.load(f)

                    # Passo 2: Troca atômica de ponteiros em memória
                    cls._instance.model = novo_modelo
                    cls._instance.scaler = novo_scaler
                    cls._instance.config = nova_config
                    cls._instance.limiar = nova_config["limiar_anomalia"]
                    cls._instance.eps_travado = nova_config.get("eps_travado", 0.0015)
                    cls._instance.clip_max = np.asarray(nova_config["clip_max"], dtype=float)
                    cls._instance.delta_std = np.asarray(nova_config["delta_std"], dtype=np.float32)
                    cls._instance.gap_max_s = nova_config.get("gap_max_s", 900.0)
                    cls._instance._modelo_mtime = (BASE_DIR / 'modelo_iqar.keras').stat().st_mtime
                    cls._instance._inferir_grafo = tf.function(
                        lambda x: cls._instance.model(x, training=False),
                        input_signature=[tf.TensorSpec(shape=[None, JANELA, 8], dtype=tf.float32)],
                    )
                    cls._instance._inferir_grafo(tf.zeros((N_JANELAS_CONFIRMACAO, JANELA, 8), dtype=tf.float32))

                    print(">>> [Agente] Hot-Reloading concluído! Novo modelo em operação.")
                    return True
                except Exception as e:
                    print(f">>> [ERRO Hot-Reloading] Falha ao recarregar: {e}. O modelo anterior foi mantido!")
                    return False
            return False

    def _normalizar(self, matriz):
        """Mesmo pipeline do treino: clip -> log1p -> MinMaxScaler."""
        return self.scaler.transform(preprocessar(matriz, self.clip_max)).astype(np.float32)

    def _verificar_hot_reload_disco(self):
        """
        Verifica se o comando `retreinar_agente` (em outro processo) promoveu um
        novo `modelo_iqar.keras` no disco e dispara o Hot-Reload automaticamente.
        """
        try:
            mtime_atual = (BASE_DIR / 'modelo_iqar.keras').stat().st_mtime
            if mtime_atual > getattr(self, '_modelo_mtime', 0):
                self.recarregar_modelo()
        except OSError:
            pass

    def avaliar_janela(self, sensor, leituras_queryset):
        from telemetria.models import AirReading, AgentAlert

        self._verificar_hot_reload_disco()

        leituras = list(leituras_queryset)
        minimo = JANELA + N_JANELAS_CONFIRMACAO - 1
        if not leituras:
            return None

        # Modo Teste é controlado EXCLUSIVAMENTE pela flag explícita APP_TESTE=1
        modo_teste = os.environ.get("APP_TESTE", "0") == "1"

        if modo_teste:
            # Em modo simulador de bancada (APP_TESTE=1), avalia por amostra direta
            if len(leituras) < minimo:
                return None
            usadas = leituras[:minimo]
            usadas.reverse()  # ordem cronológica

            tempos = [r.timestamp for r in usadas]
            dts = [(tempos[i] - tempos[i - 1]).total_seconds() for i in range(1, len(tempos))]
            if any(dt > self.gap_max_s for dt in dts):
                return None

            ultimo_ts = tempos[-1]
            co_janela = [r.co_mq135 for r in usadas]
            media_co_usadas = media_movel_co(tempos, co_janela, self.clip_max[0])
            matriz_gases = np.array([[
                r.co_mq135, r.co2_mq135, r.mh4_mq135, r.aceton_mq135,
                r.alcool_mq135, r.toluen_mq135, r.o3_mq131
            ] for r in usadas], dtype=float)
        else:
            # Em modo Produção (APP_TESTE=0), aplica resample("1min").mean() idêntico ao treinar_agente_v4.py
            # para garantir que JANELA=30 seja 30 minutos reais e HORIZONTE=15 seja +15 minutos reais!
            ultimo_ts = max(r.timestamp for r in leituras)
            oito_horas_atras = ultimo_ts - timedelta(hours=8)
            rows_8h = list(
                AirReading.objects.filter(
                    sensor=sensor,
                    timestamp__gte=oito_horas_atras,
                    timestamp__lte=ultimo_ts,
                )
                .order_by("timestamp")
                .values_list(
                    "timestamp",
                    "co_mq135", "co2_mq135", "mh4_mq135", "aceton_mq135",
                    "alcool_mq135", "toluen_mq135", "o3_mq131",
                )
            )
            if len(rows_8h) < minimo:
                return None

            df_8h = pd.DataFrame(
                rows_8h,
                columns=["timestamp"] + GASES,
            )
            df_8h["timestamp"] = pd.to_datetime(df_8h["timestamp"], utc=True)
            df_8h = df_8h.set_index("timestamp")
            df_1m = df_8h[GASES].resample("1min").mean().dropna()
            if len(df_1m) < minimo:
                return None

            df_usadas = df_1m.iloc[-minimo:]
            tempos_1m = df_usadas.index.to_pydatetime().tolist()
            dts = [(tempos_1m[i] - tempos_1m[i - 1]).total_seconds() for i in range(1, len(tempos_1m))]
            if any(dt > self.gap_max_s for dt in dts):
                return None

            media_co_total = media_movel_co(df_1m.index, df_1m["CO_MQ135"].to_numpy(), self.clip_max[0])
            media_co_usadas = media_co_total[-minimo:]
            matriz_gases = df_usadas[GASES].to_numpy(dtype=float)
        
        matriz = np.column_stack([matriz_gases, media_co_usadas])
        escalada = self._normalizar(matriz)
        n_janelas = len(escalada) - JANELA + 1
        lote = np.stack([escalada[i:i + JANELA] for i in range(n_janelas)])

        # 3. Inferência Multi-Task em lote via Grafo C++ compilado (@tf.function)
        rec_t, delta_t, class_t = self._inferir_grafo(tf.constant(lote, dtype=tf.float32))
        rec_out, delta_out, class_out = rec_t.numpy(), delta_t.numpy(), class_t.numpy()

        # 4. Anomalia: cálculo idêntico ao treino (máximo por passo temporal) + sensor travado
        # lote tem shape: (n_janelas, JANELA, 8)
        # Calcula média nos 8 canais por passo, e pega o pior passo (pico) de cada janela:
        erros = np.mean(np.abs(lote - rec_out), axis=2).max(axis=1)
        n_acima = int((erros > self.limiar).sum())
        anomalia_reconstrucao = n_acima >= min(MIN_JANELAS_ANOMALAS, n_janelas)
        erro_atual = float(erros[-1])

        # Verificação se o sensor está travado na janela mais recente (últimos 7 gases, sem média de 8h)

        desvio_recente = lote[-1, :, :7].std(axis=0)
        esta_travado = bool(desvio_recente.max() < self.eps_travado)

        # Anomalia confirmada se o Autoencoder disparar OU se o sensor estiver travado

        is_anomalia = anomalia_reconstrucao or esta_travado

        # 5. Previsão do próximo passo (última janela)
        previsto_esc = np.clip(lote[-1, -1, :] + delta_out[-1] * self.delta_std, 0.0, 1.0)
        valores_previstos = np.expm1(self.scaler.inverse_transform(previsto_esc[None, :]))[0]
        probs = class_out[-1]
        classe_idx = int(np.argmax(probs))
        nome_classe = self.classes[classe_idx]

        # 6. Regras de Decisão Autônoma do Agente com Cooldown
        alerta = None
        tipo_alerta = None
        mensagem = ""

        if is_anomalia:
            tipo_alerta = "ANOMALIA"
            if esta_travado:
                mensagem = "Anomalia detectada: sensor travado (leituras sem variação temporal detectável)!"
            else:
                mensagem = (f"Anomalia detectada nos sensores! Erro: {erro_atual:.4f} "
                            f"(Limiar: {self.limiar:.4f}; {n_acima}/{n_janelas} janelas acima)")
        elif classe_idx == 2:  # Risco de qualidade do ar "Ruim" previsto em 15 minutos
            tipo_alerta = "PREVISAO_CRITICA"
            mensagem = (f"Alerta Preditivo (15 min à frente): Risco iminente de qualidade do ar 'Ruim' "
                        f"(prob. {probs[2]:.0%}). Projeção futura de CO: {valores_previstos[0]:.2f} ppm")


        if tipo_alerta:
            cooldown_limit = ultimo_ts - timedelta(minutes=self.cooldown_minutos)
            recente = AgentAlert.objects.filter(
                sensor=sensor, 
                tipo=tipo_alerta, 
                resolvido=False,
                timestamp__gte=cooldown_limit
            ).exists()
            if not recente:
                alerta = {"tipo": tipo_alerta, "mensagem": mensagem}

        return {
            "anomalia": is_anomalia,
            "erro_reconstrucao": erro_atual,
            "classe": nome_classe,
            "probabilidades": {c: float(p) for c, p in zip(self.classes, probs)},
            "previsao": {g: float(v) for g, v in zip(self.config["features"], valores_previstos)},
            "alerta": alerta,
        }
