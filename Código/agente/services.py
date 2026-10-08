import json
import joblib
import numpy as np
import tensorflow as tf
from pathlib import Path
import threading
from datetime import timedelta

from .preprocessamento import JANELA, preprocessar, media_movel_co

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
    2. Previsão Temporal Futura (Forecasting dos gases, 1 passo à frente)
    3. Classificação do Nível da Qualidade do Ar (IQAr)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AirQualifyService, cls).__new__(cls)
                # 1. Carrega o modelo, normalizador e configurações salvas
                cls._instance.model = tf.keras.models.load_model(BASE_DIR / 'modelo_iqar.keras')
                cls._instance.scaler = joblib.load(BASE_DIR / 'scaler.pkl')

                with open(BASE_DIR / 'config_agente.json', 'r') as f:
                    cls._instance.config = json.load(f)

                cfg = cls._instance.config
                cls._instance.limiar = cfg["limiar_anomalia"]
                cls._instance.classes = cfg.get("classes", ["Boa", "Moderada", "Ruim"])
                cls._instance.clip_max = np.asarray(cfg["clip_max"], dtype=float)
                cls._instance.delta_std = np.asarray(cfg["delta_std"], dtype=np.float32)
                cls._instance.gap_max_s = cfg.get("gap_max_s", 60.0)
                cls._instance.cooldown_minutos = 15
                print(">>> [Agente Inteligente] Modelo Multi-Task Carregado com Sucesso!")
        return cls._instance

    def _normalizar(self, matriz):
        """Mesmo pipeline do treino: clip -> log1p -> MinMaxScaler."""
        return self.scaler.transform(preprocessar(matriz, self.clip_max)).astype(np.float32)

    def avaliar_janela(self, sensor, leituras_queryset):
        from telemetria.models import AirReading, AgentAlert
        
        leituras = list(leituras_queryset)
        # 1. Garante histórico mínimo (janelas de confirmação + 11 leituras anteriores)
        minimo = JANELA + N_JANELAS_CONFIRMACAO - 1
        if len(leituras) < minimo:
            return None
        usadas = leituras[:minimo]
        usadas.reverse()  # ordem cronológica

        # Verifica lacunas temporais
        tempos = [r.timestamp for r in usadas]
        dts = [(tempos[i] - tempos[i-1]).total_seconds() for i in range(1, len(tempos))]
        if any(dt > self.gap_max_s for dt in dts):
            return None

        # Calcula a média móvel de 8h do CO. Precisamos buscar o histórico de 8h.
        ultimo_ts = tempos[-1]
        oito_horas_atras = ultimo_ts - timedelta(hours=8)
        
        # Otimização: buscar apenas tempos e CO das últimas 8 horas
        leituras_8h = AirReading.objects.filter(
            sensor=sensor, 
            timestamp__gte=oito_horas_atras,
            timestamp__lte=ultimo_ts
        ).order_by('timestamp').values_list('timestamp', 'co_mq135')
        
        tempos_8h = [r[0] for r in leituras_8h]
        co_8h = [r[1] for r in leituras_8h]
        
        media_co_total = media_movel_co(tempos_8h, co_8h, self.clip_max[0])
        # Precisamos apenas das médias correspondentes às leituras 'usadas'
        media_co_usadas = media_co_total[-len(usadas):]

        # 2. Converte em matriz, normaliza e monta as janelas deslizantes
        matriz_gases = np.array([[
            r.co_mq135, r.co2_mq135, r.mh4_mq135, r.aceton_mq135,
            r.alcool_mq135, r.toluen_mq135, r.o3_mq131
        ] for r in usadas], dtype=float)
        
        matriz = np.column_stack([matriz_gases, media_co_usadas])
        escalada = self._normalizar(matriz)
        n_janelas = len(escalada) - JANELA + 1
        lote = np.stack([escalada[i:i + JANELA] for i in range(n_janelas)])

        # 3. Inferência Multi-Task em lote
        rec_out, delta_out, class_out = (np.asarray(t) for t in self.model(lote, training=False))

        # 4. Anomalia: confirmada se >= MIN_JANELAS_ANOMALAS janelas passarem do limiar
        erros = np.mean(np.abs(lote - rec_out), axis=(1, 2))
        n_acima = int((erros > self.limiar).sum())
        is_anomalia = n_acima >= min(MIN_JANELAS_ANOMALAS, n_janelas)
        erro_atual = float(erros[-1])

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
            mensagem = (f"Anomalia detectada nos sensores! Erro: {erro_atual:.4f} "
                        f"(Limiar: {self.limiar:.4f}; {n_acima}/{n_janelas} janelas acima)")
        elif classe_idx == 2:  # Risco "Ruim"
            tipo_alerta = "PREVISAO_CRITICA"
            mensagem = (f"Previsão de deterioração da qualidade do ar para 'Ruim' "
                        f"(prob. {probs[2]:.0%}). Tendência futura de CO: {valores_previstos[0]:.2f} ppm")

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
