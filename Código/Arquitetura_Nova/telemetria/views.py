from django.shortcuts import render
import csv
import json
import os
import time
from pathlib import Path
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import SensorNode, AgentAlert, AirReading, AgentPrediction
from agente.preprocessamento import CO_MODERADA, CO_RUIM

MONITORAMENTO_DIR = Path(__file__).resolve().parent.parent / "monitoramento"
CSV_LEITURAS_PATH = MONITORAMENTO_DIR / "metricas_processamento_leituras.csv"
ESTADO_AGENTE_PATH = MONITORAMENTO_DIR / "estado_agente.json"


def obter_estado_agente() -> bool:
    if ESTADO_AGENTE_PATH.exists():
        try:
            dados = json.loads(ESTADO_AGENTE_PATH.read_text(encoding="utf-8"))
            return str(dados.get("usar_agente", "1")) in ("1", "true", "True")
        except Exception:
            pass
    return os.environ.get("USAR_AGENTE", "1") == "1"


def classificar_co_reativo(co_val: float) -> str:
    if co_val >= CO_RUIM:
        return "Ruim"
    elif co_val >= CO_MODERADA:
        return "Moderada"
    return "Boa"


def registrar_metrica_leitura(linha: dict):
    try:
        MONITORAMENTO_DIR.mkdir(parents=True, exist_ok=True)
        arquivo_existe = CSV_LEITURAS_PATH.exists()
        campos = [
            "timestamp_recebimento",
            "timestamp_sensor",
            "arquitetura",
            "usar_agente",
            "dev_eui",
            "co_atual",
            "iqar_reativo_presente",
            "alerta_reativo_presente",
            "iqar_previsto_15m",
            "co_previsto_15m",
            "anomalia_detectada",
            "erro_reconstrucao",
            "tipo_alerta_agente",
            "latencia_total_ms",
            "latencia_agente_ms",
        ]
        with open(CSV_LEITURAS_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            if not arquivo_existe:
                writer.writeheader()
            writer.writerow(linha)
    except Exception as e:
        print(f">>> [Aviso Monitoramento] Falha ao gravar CSV de métricas: {e}")


@csrf_exempt
def chirpstack_webhook(request):
    t_inicio_total = time.perf_counter()

    if request.method != "POST":
        return JsonResponse({"error": f"O metodo {request.method} não é permitido"}, status=405)

    # Ignora eventos do ChirpStack que não sejam uplink de dados (ex: join, status, ack, log)
    evento = request.GET.get("event")
    if evento and evento != "up":
        print(f">>> [Webhook ChirpStack] Evento '{evento}' recebido e confirmado (200 OK).")
        return JsonResponse({"status": "evento_ignorado", "event": evento}, status=200)

    try:
        data = json.loads(request.body)

        # Passo numero 1: Extrai o identificador do sensor do chirpstack
        device_info = data.get("deviceInfo", {})
        dev_eui = device_info.get("devEui") or data.get("devEui")
        device_name = device_info.get("deviceName") or device_info.get("devicename") or "Sensor_Galpao_lab"
        time_str = data.get("time") or timezone.now().isoformat()
        obj = data.get("object", {})

        if not dev_eui or not obj:
            return JsonResponse({"error": "Payload sem devEui ou dados dos sensores"}, status=400)

        # Passo numero 2: Registra o Local do nó sensor
        sensor, _ = SensorNode.objects.get_or_create(
            dev_eui=dev_eui,
            defaults={"nome": device_name}
        )

        # Passo numero 3: Salva a nova Leitura (ignora se faltarem dados)
        co = obj.get("CO_MQ135")
        if co is None:
            return JsonResponse({"error": "Payload sem dados essenciais"}, status=400)

        co_float = float(co)
        AirReading.objects.create(
            sensor=sensor,
            timestamp=time_str,
            co_mq135=co_float,
            co2_mq135=float(obj.get("CO2_MQ135", 0.0)),
            mh4_mq135=float(obj.get("MH4_MQ135", 0.0)),
            aceton_mq135=float(obj.get("Aceton_MQ135", 0.0)),
            alcool_mq135=float(obj.get("Alcool_MQ135", 0.0)),
            toluen_mq135=float(obj.get("Toluen_MQ135", 0.0)),
            o3_mq131=float(obj.get("O3_MQ131", 0.0))
        )

        # Avaliação Reativa (Poluição Presente - Sem Agente)
        iqar_reativo = classificar_co_reativo(co_float)
        alerta_reativo = iqar_reativo == "Ruim"

        usar_agente = obter_estado_agente()
        print(
            f">>> [Webhook] Leitura salva no PostgreSQL! Sensor={device_name} ({dev_eui}) | "
            f"CO={co_float:.2f} ppm (IQAr Presente={iqar_reativo}) | "
            f"CO2={obj.get('CO2_MQ135')} | O3={obj.get('O3_MQ131')} | USAR_AGENTE={int(usar_agente)}"
        )
        if alerta_reativo:
            print(f">>> [AVISO REATIVO - POLUICAO PRESENTE] CO atual ({co_float:.2f} ppm) atingiu nivel RUIM (>={CO_RUIM} ppm)!")

        iqar_previsto = ""
        prev_co = ""
        anomalia_bool = ""
        erro_rec = ""
        tipo_alerta_agente = ""
        latencia_agente_ms = 0.0

        # Passo numero 4: Aciona o Agente Inteligente somente se USAR_AGENTE=1
        if usar_agente:
            from agente.services import AirQualifyService
            t_inicio_agente = time.perf_counter()
            ultimas_leituras = list(AirReading.objects.filter(sensor=sensor).order_by('-timestamp')[:40])
            agente = AirQualifyService()
            resultado = agente.avaliar_janela(sensor, ultimas_leituras)
            latencia_agente_ms = (time.perf_counter() - t_inicio_agente) * 1000.0

            if resultado:
                probs = resultado.get("probabilidades", {})
                prev_co_val = resultado["previsao"].get("CO_MQ135", 0.0)
                iqar_previsto = resultado["classe"]
                prev_co = f"{prev_co_val:.4f}"
                anomalia_bool = int(bool(resultado["anomalia"]))
                erro_rec = f"{resultado['erro_reconstrucao']:.6f}"

                print(
                    f">>> [Agente IA] IQAr Previsto (15m): {iqar_previsto} "
                    f"(Boa={probs.get('Boa', 0):.0%}, Mod={probs.get('Moderada', 0):.0%}, Ruim={probs.get('Ruim', 0):.0%}) | "
                    f"CO Previsto={prev_co_val:.2f} ppm | Erro Rec={resultado['erro_reconstrucao']:.4f} | "
                    f"Anomalia={resultado['anomalia']} | Tempo Agente={latencia_agente_ms:.2f} ms"
                )
                AgentPrediction.objects.create(
                    sensor=sensor,
                    anomalia=resultado["anomalia"],
                    erro_reconstrucao=resultado["erro_reconstrucao"],
                    classe_iqar=iqar_previsto,
                    previsao_co=prev_co_val
                )

                alerta = resultado.get("alerta")
                if alerta:
                    tipo_alerta_agente = alerta["tipo"]
                    print(f">>> [ALERTA AGENTE IA] [{alerta['tipo']}] {alerta['mensagem']}")
                    AgentAlert.objects.create(
                        sensor=sensor,
                        tipo=alerta["tipo"],
                        mensagem=alerta["mensagem"]
                    )
            else:
                print(f">>> [Agente IA] Coletando janela inicial de leituras ({len(ultimas_leituras)}/32)...")
        else:
            print(">>> [Modo SEM AGENTE] Inferencia IA desativada (USAR_AGENTE=0). Apenas monitoramento reativo de poluicao presente.")

        latencia_total_ms = (time.perf_counter() - t_inicio_total) * 1000.0

        registrar_metrica_leitura({
            "timestamp_recebimento": timezone.now().isoformat(),
            "timestamp_sensor": str(time_str),
            "arquitetura": "Arquitetura_Nova",
            "usar_agente": int(usar_agente),
            "dev_eui": dev_eui,
            "co_atual": f"{co_float:.4f}",
            "iqar_reativo_presente": iqar_reativo,
            "alerta_reativo_presente": int(alerta_reativo),
            "iqar_previsto_15m": iqar_previsto,
            "co_previsto_15m": prev_co,
            "anomalia_detectada": anomalia_bool,
            "erro_reconstrucao": erro_rec,
            "tipo_alerta_agente": tipo_alerta_agente,
            "latencia_total_ms": f"{latencia_total_ms:.3f}",
            "latencia_agente_ms": f"{latencia_agente_ms:.3f}",
        })

        return JsonResponse({
            "status": "sucesso",
            "sensor": dev_eui,
            "usar_agente": usar_agente,
            "iqar_reativo_presente": iqar_reativo,
            "latencia_total_ms": round(latencia_total_ms, 3),
            "latencia_agente_ms": round(latencia_agente_ms, 3),
        }, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
