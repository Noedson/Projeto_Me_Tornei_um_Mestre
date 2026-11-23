import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, Client
from telemetria.models import SensorNode, AirReading
import monitorar_recursos_docker as monitor


class WebhookQAAuditTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = "/api/chirpstack/webhook/?event=up"
        self.payload_valido = {
            "deviceInfo": {
                "devEui": "d3afdcdc546af01d",
                "deviceName": "Sensor_QA_Lab",
            },
            "time": "2026-11-19T15:00:00+00:00",
            "object": {
                "CO_MQ135": 2.15,
                "CO2_MQ135": 1.80,
                "MH4_MQ135": 0.95,
                "Aceton_MQ135": 0.45,
                "Alcool_MQ135": 0.60,
                "Toluen_MQ135": 0.35,
                "O3_MQ131": 0.75,
            },
        }

    @patch("telemetria.views.registrar_metrica_leitura")
    @patch("telemetria.views.obter_estado_agente", return_value=False)
    def test_achado_7_rejeita_gas_ausente_sem_gravar_zero(self, _mock_agente, _mock_metrica):
        """Achado #7: Se faltar qualquer um dos 7 gases, deve retornar 400 e não gravar 0.0 no banco."""
        payload_incompleto = json.loads(json.dumps(self.payload_valido))
        del payload_incompleto["object"]["O3_MQ131"]

        resp = self.client.post(
            self.url,
            data=json.dumps(payload_incompleto),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("O3_MQ131", resp.json().get("error", ""))
        self.assertEqual(AirReading.objects.count(), 0)

    @patch("telemetria.views.registrar_metrica_leitura")
    @patch("telemetria.views.obter_estado_agente", return_value=False)
    def test_achado_7_rejeita_valor_negativo_ou_invalido(self, _mock_agente, _mock_metrica):
        """Achado #7: Valores negativos ou não-numéricos nos gases devem retornar 400."""
        payload_negativo = json.loads(json.dumps(self.payload_valido))
        payload_negativo["object"]["CO2_MQ135"] = -5.0

        resp = self.client.post(
            self.url,
            data=json.dumps(payload_negativo),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AirReading.objects.count(), 0)

    @patch("telemetria.views.registrar_metrica_leitura")
    @patch("telemetria.views.obter_estado_agente", return_value=False)
    def test_achado_6_idempotencia_duplicata_lorawan(self, _mock_agente, _mock_metrica):
        """Achado #6: Reenvio do mesmo (sensor, timestamp) pelo ChirpStack deve ser ignorado sem duplicar."""
        resp1 = self.client.post(
            self.url,
            data=json.dumps(self.payload_valido),
            content_type="application/json",
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json().get("status"), "sucesso")
        self.assertEqual(AirReading.objects.count(), 1)

        resp2 = self.client.post(
            self.url,
            data=json.dumps(self.payload_valido),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get("status"), "duplicata_ignorada")
        self.assertEqual(AirReading.objects.count(), 1)


class MonitorRecursosQAAuditTests(TestCase):
    def test_achado_10_exclui_simulador_do_total_arquitetura(self):
        """Achado #10: smart_campus_lwn_simulator deve estar na lista de exclusão do monitor."""
        self.assertIn("smart_campus_lwn_simulator", monitor.CONTAINERS_EXCLUIDOS)

    def test_backup_completo_incremental_e_resgate_sqlite(self):
        """Valida ciclo completo: 1º Backup Completo -> 2º Incremental -> Resgate sem perda."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_ativo = tmp_path / "metricas_experimento.db"
            db_backup = tmp_path / "backup_metricas_experimento.db"
            estado_path = tmp_path / "estado_agente.json"

            with patch.object(monitor, "MONITORAMENTO_DIR", tmp_path), \
                 patch.object(monitor, "DB_PATH", db_ativo), \
                 patch.object(monitor, "BACKUP_DB_PATH", db_backup), \
                 patch.object(monitor, "ESTADO_AGENTE_PATH", estado_path):

                monitor.inicializar_sqlite()
                monitor.salvar_estado_agente("1")
                self.assertEqual(monitor.ler_estado("0"), "1")

                monitor.salvar_amostras_sqlite([{
                    "timestamp": "2026-11-19T15:00:00-03:00",
                    "arquitetura": "Arquitetura_Nova",
                    "usar_agente": 1,
                    "container": "TOTAL_ARQUITETURA",
                    "cpu_percent": 12.5,
                    "mem_usage_mb": 512.0,
                    "mem_limit_mb": 4096.0,
                    "net_rx_kbps": 8.2,
                    "net_tx_kbps": 4.1,
                    "block_read_mb": 0.1,
                    "block_write_mb": 0.2,
                    "pids": 45,
                }])

                # 1ª vez: deve ser backup_completo
                r1 = monitor.fazer_backup_e_zerar_sqlite()
                self.assertTrue(r1["ok"])
                self.assertEqual(r1["modo"], "backup_completo")
                self.assertEqual(r1["total_recursos_backup"], 1)

                # Insere nova amostra e roda 2ª vez: deve ser atualizacao_incremental
                monitor.salvar_amostras_sqlite([{
                    "timestamp": "2026-11-19T15:00:05-03:00",
                    "arquitetura": "Arquitetura_Nova",
                    "usar_agente": 1,
                    "container": "TOTAL_ARQUITETURA",
                    "cpu_percent": 14.0,
                    "mem_usage_mb": 515.0,
                    "mem_limit_mb": 4096.0,
                    "net_rx_kbps": 9.0,
                    "net_tx_kbps": 4.5,
                    "block_read_mb": 0.1,
                    "block_write_mb": 0.3,
                    "pids": 45,
                }])
                r2 = monitor.fazer_backup_e_zerar_sqlite()
                self.assertTrue(r2["ok"])
                self.assertEqual(r2["modo"], "atualizacao_incremental")
                self.assertEqual(r2["novos_recursos_backup"], 1)
                self.assertEqual(r2["total_recursos_backup"], 2)

                # Resgate: deve restaurar as 2 amostras para o banco ativo
                resgate = monitor.resgatar_backup_sqlite()
                self.assertTrue(resgate["ok"])
                self.assertEqual(resgate["recursos_restaurados"], 2)
                self.assertEqual(resgate["total_recursos_ativo"], 2)
