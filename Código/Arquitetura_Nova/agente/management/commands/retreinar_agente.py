import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone as dt_timezone

import pandas as pd
from django.core.management.base import BaseCommand
from django.utils import timezone

from telemetria.models import AirReading
from agente.models import ConfiguracaoRetreino
from agente.services import AirQualifyService, BASE_DIR
from agente.preprocessamento import GASES, JANELA, HORIZONTE


class Command(BaseCommand):
    help = "Retreina o agente inteligente executando o pipeline oficial V4 (treinar_agente_v4.py) com validação de gatekeeper e hot-reload."

    def add_arguments(self, parser):
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Força o retreino mesmo se desativado no Django Admin ou se houver poucas amostras no banco.",
        )
        parser.add_argument(
            "--epocas",
            type=int,
            default=50,
            help="Número máximo de épocas para o retreino (padrão: 50). O Early Stopping permanece sempre ativo.",
        )
        parser.add_argument(
            "--patience",
            type=int,
            default=8,
            help="Paciência do Early Stopping (padrão: 8). O treinamento para antes caso o modelo pare de evoluir.",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=128,
            help="Tamanho do batch para o treinamento (padrão: 128).",
        )
        parser.add_argument(
            "--ignorar-banco",
            action="store_true",
            help="Ignora novas leituras do banco PostgreSQL e retreina apenas com a base histórica 'event_up.csv'.",
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 65)
        self.stdout.write(">>> [Retreino Agente V4] Iniciando ciclo de retreinamento oficial...")
        self.stdout.write("=" * 65)

        # -------------------------------------------------------------
        # 1. Consulta o Django Admin: O retreino está ativo?
        # -------------------------------------------------------------
        config, _ = ConfiguracaoRetreino.objects.get_or_create(id=1)

        if not config.ativo and not options["forcar"]:
            self.stdout.write(
                self.style.WARNING(
                    ">>> [PAINEL ADMIN] O retreinamento automático está DESATIVADO pelo gestor.\n"
                    ">>> (Para forçar manualmente a execução, utilize o argumento --forcar). Abortando."
                )
            )
            return

        # -------------------------------------------------------------
        # 2. Sincronização Temporal Oficial via Protocolo NTP
        # -------------------------------------------------------------
        hora_referencia = timezone.now()
        if config.usar_ntp:
            try:
                import ntplib
                cliente_ntp = ntplib.NTPClient()
                resposta = cliente_ntp.request(config.servidor_ntp, version=3, timeout=4)
                hora_referencia = datetime.fromtimestamp(resposta.tx_time, tz=dt_timezone.utc)
                self.stdout.write(
                    self.style.SUCCESS(
                        f">>> [NTP Sincronizado] Horário oficial obtido via {config.servidor_ntp}: {hora_referencia}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f">>> [Aviso NTP] Falha ao consultar servidor NTP ({e}). Utilizando horário local do sistema."
                    )
                )

        # -------------------------------------------------------------
        # 3. Extração dos Dados Recentes do Banco Django (se houver)
        # -------------------------------------------------------------
        arquivo_extra_csv = None
        temp_csv_path = BASE_DIR / "novas_leituras_retreino_temp.csv"

        if not options["ignorar_banco"]:
            intervalo_h = config.intervalo_horas
            limite_de_tempo = hora_referencia - timedelta(hours=intervalo_h)
            self.stdout.write(f">>> Verificando leituras no banco das últimas {intervalo_h}h (desde {limite_de_tempo})...")

            try:
                leituras_qs = AirReading.objects.filter(timestamp__gte=limite_de_tempo).order_by("timestamp")
                total_leituras = leituras_qs.count()
                min_amostras = JANELA + HORIZONTE + 100

                if total_leituras >= min_amostras or (options["forcar"] and total_leituras > 0):
                    self.stdout.write(
                        self.style.SUCCESS(
                            f">>> Exportando {total_leituras} leituras recentes do banco para incorporar ao retreino V4..."
                        )
                    )
                    dados = []
                    for l in leituras_qs:
                        dados.append({
                            "Time": l.timestamp.isoformat(),
                            "CO_MQ135": l.co_mq135,
                            "CO2_MQ135": l.co2_mq135,
                            "MH4_MQ135": l.mh4_mq135,
                            "Aceton_MQ135": l.aceton_mq135,
                            "Alcool_MQ135": l.alcool_mq135,
                            "Toluen_MQ135": l.toluen_mq135,
                            "O3_MQ131": l.o3_mq131,
                        })
                    df_novos = pd.DataFrame(dados)
                    df_novos.to_csv(temp_csv_path, index=False)
                    arquivo_extra_csv = temp_csv_path
                else:
                    self.stdout.write(
                        self.style.NOTICE(
                            f">>> Banco possui {total_leituras} leituras recentes (< {min_amostras}). "
                            "Executando retreino com a base histórica completa 'event_up.csv'."
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f">>> Aviso ao consultar banco ({e}). Prosseguindo com o dataset histórico padrão."
                    )
                )

        # -------------------------------------------------------------
        # 4. Backup Preventivo do Modelo Atual (Rollback em caso de falha)
        # -------------------------------------------------------------
        caminho_oficial = BASE_DIR / "modelo_iqar.keras"
        caminho_backup = BASE_DIR / "modelo_iqar_backup.keras"
        caminho_cfg = BASE_DIR / "config_agente.json"
        caminho_cfg_backup = BASE_DIR / "config_agente_backup.json"

        if caminho_oficial.exists():
            shutil.copy2(caminho_oficial, caminho_backup)
        if caminho_cfg.exists():
            shutil.copy2(caminho_cfg, caminho_cfg_backup)

        # -------------------------------------------------------------
        # 5. Execução do Retreino via Pipeline Oficial V4 (subprocess isolado)
        # -------------------------------------------------------------
        script_v4 = Path(BASE_DIR).parent / "treinar_agente_v4.py"
        epocas = options["epocas"]
        batch = options["batch"]

        comando = [
            sys.executable,
            str(script_v4),
            "--epocas",
            str(epocas),
            "--batch",
            str(batch),
            "--patience",
            str(options["patience"]),
        ]
        if arquivo_extra_csv:
            comando.extend(["--extra-csv", str(arquivo_extra_csv)])

        self.stdout.write(
            f">>> Disparando: {' '.join(comando)} "
            f"(Early Stopping SEMPRE ATIVO: monitor='val_loss', paciência={options['patience']})"
        )
        self.stdout.write("-" * 65)

        try:
            resultado = subprocess.run(comando, cwd=str(script_v4.parent))
            sucesso_processo = (resultado.returncode == 0)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f">>> [ERRO] Falha ao executar processo do V4: {e}"))
            sucesso_processo = False
        finally:
            # Limpeza do CSV temporário se tiver sido criado
            if temp_csv_path.exists():
                try:
                    temp_csv_path.unlink()
                except OSError:
                    pass

        if not sucesso_processo:
            self.stdout.write(self.style.ERROR(">>> [ERRO CRÍTICO] O script 'treinar_agente_v4' retornou código de erro."))
            if caminho_backup.exists():
                shutil.copy2(caminho_backup, caminho_oficial)
                self.stdout.write(">>> Backup do modelo anterior restaurado com sucesso.")
            return

        # -------------------------------------------------------------
        # 6. GATEKEEPER DE QUALIDADE: Validação antes de Promover
        # -------------------------------------------------------------
        metricas_path = BASE_DIR / "metricas_finais.json"
        acc_nova = 0.0

        if metricas_path.exists():
            try:
                with open(metricas_path, "r", encoding="utf-8") as f:
                    relatorio = json.load(f)
                acc_nova = float(relatorio["classificacao"]["acuracia_modelo"])
            except Exception as e:
                self.stdout.write(self.style.WARNING(f">>> Falha ao ler métricas finais: {e}"))

        corte_minimo = float(config.acuracia_minima_gatekeeper)
        self.stdout.write("-" * 65)
        self.stdout.write(f">>> Acurácia atingida pelo V4: {acc_nova:.2%} (Mínimo exigido: {corte_minimo:.2%})")

        if acc_nova < corte_minimo:
            self.stdout.write(
                self.style.ERROR(
                    f">>> [GATEKEEPER REPROVOU] Acurácia ({acc_nova:.2%}) ficou abaixo do limite exigido ({corte_minimo:.2%}). "
                    "Restaurando modelo anterior. Nenhum modelo com desempenho inferior foi para produção."
                )
            )
            if caminho_backup.exists():
                shutil.copy2(caminho_backup, caminho_oficial)
            if caminho_cfg_backup.exists():
                shutil.copy2(caminho_cfg_backup, caminho_cfg)
            return

        self.stdout.write(self.style.SUCCESS(">>> [GATEKEEPER APROVOU] Novo modelo V4 atingiu os critérios de excelência!"))

        # Remove backups preventivos pois o novo modelo foi promovido com sucesso
        if caminho_backup.exists():
            caminho_backup.unlink()
        if caminho_cfg_backup.exists():
            caminho_cfg_backup.unlink()

        # -------------------------------------------------------------
        # 7. Disparo do Hot-Reloading no Django e Registro de Sucesso
        # -------------------------------------------------------------
        recarregou = AirQualifyService.recarregar_modelo()
        config.ultimo_retreino_sucesso = hora_referencia
        config.save()

        if recarregou:
            self.stdout.write(
                self.style.SUCCESS(
                    ">>> [SUCESSO COMPLETO] Retreino V4, Validação Gatekeeper e Hot-Reloading finalizados com Zero Downtime!"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    ">>> [SUCESSO COMPLETO] Retreino V4 e Gatekeeper finalizados! "
                    "Novos artefatos e gráficos gerados prontos para as próximas inferências."
                )
            )