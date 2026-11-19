import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase
from telemetria.models import SensorNode, AirReading
from agente.services import AirQualifyService, BASE_DIR


class AgenteQAAuditTests(TestCase):
    def setUp(self):
        self.sensor = SensorNode.objects.create(
            dev_eui="d3afdcdc546af01d",
            nome="Sensor_QA_Agente",
        )
        self.agente = AirQualifyService()

    def _criar_leituras(self, n_amostras: int, passo_segundos: int):
        base_ts = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
        objs = []
        for i in range(n_amostras):
            objs.append(
                AirReading(
                    sensor=self.sensor,
                    timestamp=base_ts + timedelta(seconds=i * passo_segundos),
                    co_mq135=2.0 + (i % 5) * 0.05,
                    co2_mq135=1.6 + (i % 3) * 0.02,
                    mh4_mq135=0.9,
                    aceton_mq135=0.4,
                    alcool_mq135=0.5,
                    toluen_mq135=0.3,
                    o3_mq131=0.7,
                )
            )
        AirReading.objects.bulk_create(objs)

    def test_achados_1_e_2_modo_producao_exige_32_minutos_reais_reamostrados(self):
        """
        Achados #1 e #2: Em modo produção (APP_TESTE=0), 32 leituras espaçadas em 5s
        cobrem apenas ~2.5 minutos. Após resample('1min'), resultam em apenas 3 minutos (< 32),
        portanto avaliar_janela() DEVE retornar None (e NÃO cair em modo_teste por dt_mediano <= 20s).
        """
        self._criar_leituras(n_amostras=32, passo_segundos=5)
        ultimas = list(AirReading.objects.filter(sensor=self.sensor).order_by("-timestamp")[:32])

        with patch.dict(os.environ, {"APP_TESTE": "0"}):
            resultado_prod = self.agente.avaliar_janela(self.sensor, ultimas)
            self.assertIsNone(resultado_prod)

        # Já com APP_TESTE=1 explícito (modo simulador de bancada), as mesmas 32 amostras são avaliadas
        with patch.dict(os.environ, {"APP_TESTE": "1"}):
            resultado_sim = self.agente.avaliar_janela(self.sensor, ultimas)
            self.assertIsNotNone(resultado_sim)
            self.assertIn("classe", resultado_sim)
            self.assertIn("erro_reconstrucao", resultado_sim)

    def test_achado_1_modo_producao_avalia_corretamente_com_35_minutos_de_historico(self):
        """
        Achado #1: Em modo produção (APP_TESTE=0), quando há >= 32 minutos reais de histórico
        (ex: 70 leituras a cada 30s = 35 minutos), o resample('1min') produz >= 32 passos de 1 min
        e realiza a inferência real de +15 minutos à frente.
        """
        self._criar_leituras(n_amostras=70, passo_segundos=30)
        ultimas = list(AirReading.objects.filter(sensor=self.sensor).order_by("-timestamp")[:32])

        with patch.dict(os.environ, {"APP_TESTE": "0"}):
            resultado_prod = self.agente.avaliar_janela(self.sensor, ultimas)
            self.assertIsNotNone(resultado_prod)
            self.assertIn(resultado_prod["classe"], ["Boa", "Moderada", "Ruim"])
            self.assertIn("CO_MQ135", resultado_prod["previsao"])

    def test_achado_3_hot_reload_automatico_por_mtime(self):
        """
        Achado #3: Quando o mtime de modelo_iqar.keras avança no disco (simulando promoção
        pelo comando retreinar_agente em outro processo), _verificar_hot_reload_disco()
        deve disparar recarregar_modelo() automaticamente.
        """
        self.agente._modelo_mtime = 0.0
        with patch.object(AirQualifyService, "recarregar_modelo", return_value=True) as mock_reload:
            self.agente._verificar_hot_reload_disco()
            mock_reload.assert_called_once()
        # Restaura o mtime real
        self.agente._modelo_mtime = (BASE_DIR / "modelo_iqar.keras").stat().st_mtime
