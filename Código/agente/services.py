import json
import joblib
import numpy as np
import tensorflow as tf
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class AirQualifyService:
    """
    Agente Inteligente Multi-Task:
    Carrega o modelo treinado uma única vez (Singleton) e avalia:
    1. Detecção de Anomalias (Erro de Reconstrução)
    2. Previsão Temporal Futura (Forecasting dos 7 gases)
    3. Classificação do Nível da Qualidade do Ar (IQAr)
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AirQualifyService, cls).__new__(cls)
            # 1. Carrega o modelo, normalizador e configurações salvas
            cls._instance.model = tf.keras.models.load_model(BASE_DIR / 'modelo_iqar.keras')
            cls._instance.scaler = joblib.load(BASE_DIR / 'scaler.pkl')
            
            with open(BASE_DIR / 'config_agente.json', 'r') as f:
                cls._instance.config = json.load(f)
                
            cls._instance.limiar = cls._instance.config.get("limiar_anomalia", 0.05)
            cls._instance.classes = cls._instance.config.get("classes", ["Boa", "Moderada", "Ruim"])
            print(">>> [Agente Inteligente] Modelo Multi-Task Carregado com Sucesso!")
        return cls._instance

    def avaliar_janela(self, sensor, leituras_queryset):
        # 1. Garante 12 leituras de histórico
        if len(leituras_queryset) < 12:
            return None

        # 2. Converte as 12 leituras em ordem cronológica
        matriz = np.array([[
            r.co_mq135, r.co2_mq135, r.mh4_mq135, r.aceton_mq135,
            r.alcool_mq135, r.toluen_mq135, r.o3_mq131
        ] for r in reversed(leituras_queryset)])

        # 3. Normalização
        matriz_scaled = self.scaler.transform(matriz)
        tensor_input = np.expand_dims(matriz_scaled, axis=0) # Shape: (1, 12, 7)

        # 4. Inferência Multi-Task em tempo real (Uma única passagem na rede!)
        rec_out, fore_out, class_out = self.model.predict(tensor_input, verbose=0)

        # 5. Avalia Anomalia
        erro_reconstrucao = float(np.mean(np.abs(matriz_scaled - rec_out[0])))
        is_anomalia = erro_reconstrucao > self.limiar

        # 6. Avalia Previsão Futura e Classe
        valores_previstos = self.scaler.inverse_transform(fore_out)[0]
        classe_idx = int(np.argmax(class_out[0]))
        nome_classe = self.classes[classe_idx]

        # 7. Regras de Decisão Autônoma do Agente
        alerta = None
        if is_anomalia:
            alerta = {
                "tipo": "ANOMALIA",
                "mensagem": f"Anomalia crítica detectada nos sensores! Erro: {erro_reconstrucao:.4f} (Limiar: {self.limiar:.4f})"
            }
        elif classe_idx == 2:  # Risco "Ruim" previsto
            co_futuro = valores_previstos[0]
            alerta = {
                "tipo": "PREVISAO_CRITICA",
                "mensagem": f"Previsão de deterioração da qualidade do ar para 'Ruim'. Tendência futura de CO: {co_futuro:.2f} ppm"
            }

        return alerta
