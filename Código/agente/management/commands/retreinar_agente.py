import json
import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from pathlib import Path
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone

from telemetria.models import AirReading
from agente.models import ConfiguracaoRetreino
from agente.services import AirQualifyService, BASE_DIR
from agente.preprocessamento import (
    GASES,
    JANELA,
    HORIZONTE,
    media_movel_co,
    preprocessar,
    classificar_co,
)


class Command(BaseCommand):
    help = "Retreina o agente periodicamente usando o modelo atual + dados recentes com validação e hot-reload."

    def handle(self, *args, **options):
        self.stdout.write("=" * 65)
        self.stdout.write(">>> [Retreino Agente] Iniciando ciclo de retreinamento contínuo...")
        self.stdout.write("=" * 65)

        # -------------------------------------------------------------
        # 1. Consulta o Django Admin: O retreino está ativo?
        # -------------------------------------------------------------
        config, _ = ConfiguracaoRetreino.objects.get_or_create(id=1)

        if not config.ativo:
            self.stdout.write(
                self.style.WARNING(
                    ">>> [PAINEL ADMIN] O retreinamento automático está DESATIVADO pelo gestor. Abortando execução."
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

        intervalo_h = config.intervalo_horas
        limite_de_tempo = hora_referencia - timedelta(hours=intervalo_h)
        self.stdout.write(f">>> Buscando leituras das últimas {intervalo_h}h (desde {limite_de_tempo})...")

        # -------------------------------------------------------------
        # 3. Extração dos Dados Recentes do Banco Django
        # -------------------------------------------------------------
        leituras_qs = AirReading.objects.filter(timestamp__gte=limite_de_tempo).order_by("timestamp")
        min_amostras = JANELA + HORIZONTE + 100

        if leituras_qs.count() < min_amostras:
            self.stdout.write(
                self.style.WARNING(
                    f">>> Amostras insuficientes no banco ({leituras_qs.count()} < {min_amostras} necessárias). Abortando."
                )
            )
            return

        dados = []
        for l in leituras_qs:
            dados.append({
                "Time": l.timestamp,
                "CO_MQ135": l.co_mq135,
                "CO2_MQ135": l.co2_mq135,
                "MH4_MQ135": l.mh4_mq135,
                "Aceton_MQ135": l.aceton_mq135,
                "Alcool_MQ135": l.alcool_mq135,
                "Toluen_MQ135": l.toluen_mq135,
                "O3_MQ131": l.o3_mq131,
            })

        df_novos = (
            pd.DataFrame(dados)
            .set_index("Time")
            .resample("1min")
            .median()
            .interpolate("time")
        )

        # -------------------------------------------------------------
        # 4. Carrega o Modelo Atual como Base (Warm-Start / Fine-Tuning)
        # -------------------------------------------------------------
        self.stdout.write(">>> Carregando modelo e scaler oficiais atuais...")
        caminho_oficial = BASE_DIR / "modelo_iqar_v4.keras"
        caminho_scaler = BASE_DIR / "scaler.pkl"
        caminho_cfg = BASE_DIR / "config_agente.json"

        if not caminho_oficial.exists():
            self.stdout.write(self.style.ERROR(f">>> Arquivo de modelo não encontrado: {caminho_oficial}"))
            return

        modelo = tf.keras.models.load_model(caminho_oficial, compile=False)
        scaler = joblib.load(caminho_scaler)

        with open(caminho_cfg, "r") as f:
            cfg = json.load(f)
        clip_max = np.asarray(cfg["clip_max"], dtype=float)

        # -------------------------------------------------------------
        # 5. Normalização com o Scaler Oficial
        # -------------------------------------------------------------
        filtrado = df_novos[GASES].rolling(5, min_periods=1, center=False).median().values
        co_media_in = media_movel_co(df_novos.index, filtrado[:, 0], clip_max[0])
        pre_in = preprocessar(np.column_stack([filtrado, co_media_in]), clip_max)
        X_novos_escalados = scaler.transform(pre_in).astype(np.float32)

        # -------------------------------------------------------------
        # 6. Montagem das Janelas Temporais
        # -------------------------------------------------------------
        X, y_rec, y_cls = [], [], []
        n = len(X_novos_escalados)
        classes_reais = classificar_co(co_media_in)

        for i in range(n - JANELA - HORIZONTE):
            X.append(X_novos_escalados[i:i + JANELA])
            y_rec.append(X_novos_escalados[i:i + JANELA])
            y_cls.append(classes_reais[i + JANELA + HORIZONTE - 1])

        X = np.asarray(X, dtype=np.float32)
        y_rec = np.asarray(y_rec, dtype=np.float32)
        y_cls = np.asarray(y_cls, dtype=int)

        if len(X) < 50:
            self.stdout.write(self.style.WARNING(">>> Poucas janelas úteis geradas para retreino. Abortando."))
            return

        # -------------------------------------------------------------
        # 7. Recompilação com Taxa Suave (1e-4) para Ajuste Fino
        # -------------------------------------------------------------
        modelo.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=1e-4),
            loss={"saida_anomalia": "mse", "saida_iqar": "sparse_categorical_crossentropy"},
            metrics={"saida_iqar": "accuracy"},
        )

        self.stdout.write(f">>> Executando Fine-Tuning em {len(X)} janelas (5 épocas)...")
        hist = modelo.fit(X, [y_rec, y_cls], epochs=5, batch_size=64, verbose=0)

        # -------------------------------------------------------------
        # 8. GATEKEEPER DE QUALIDADE: Validação antes de Promover
        # -------------------------------------------------------------
        acc_nova = float(hist.history["saida_iqar_accuracy"][-1])
        corte_minimo = float(config.acuracia_minima_gatekeeper)
        self.stdout.write(f">>> Acurácia atingida no retreino: {acc_nova:.2%} (Mínimo exigido: {corte_minimo:.2%})")

        if acc_nova < corte_minimo:
            self.stdout.write(
                self.style.ERROR(
                    f">>> [GATEKEEPER REPROVOU] Acurácia ({acc_nova:.2%}) ficou abaixo do mínimo ({corte_minimo:.2%}). "
                    "Nenhum arquivo foi modificado. O modelo atual continua em produção intacto."
                )
            )
            return

        # -------------------------------------------------------------
        # 9. Promoção Atômica de Arquivos
        # -------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS(">>> [GATEKEEPER APROVOU] Modelo novo atingiu o padrão de qualidade!"))
        caminho_candidato = BASE_DIR / "modelo_iqar_v4_candidato.keras"
        modelo.save(caminho_candidato)

        if caminho_candidato.exists():
            caminho_candidato.replace(caminho_oficial)
            self.stdout.write(f">>> Arquivo oficial substituído atomicamente: {caminho_oficial.name}")

        # -------------------------------------------------------------
        # 10. Disparo do Hot-Reloading no Django e Registro de Sucesso
        # -------------------------------------------------------------
        recarregou = AirQualifyService.recarregar_modelo()
        if recarregou:
            config.ultimo_retreino_sucesso = hora_referencia
            config.save()
            self.stdout.write(
                self.style.SUCCESS(
                    ">>> [SUCESSO COMPLETO] Retreino, Validação e Hot-Reloading finalizados com Zero Downtime!"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(">>> Modelo salvo em disco, mas a instância em memória ainda não havia sido instanciada.")
            )