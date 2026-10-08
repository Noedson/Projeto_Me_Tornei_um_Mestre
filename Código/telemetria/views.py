from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import SensorNode, AgentAlert, AirReading, AgentPrediction
from agente.services import AirQualifyService

@csrf_exempt
def chirpstack_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": f"O metodo {request.method} não é permitido"}, status=405)

    try:
        data = json.loads(request.body)

        #Passo numero 1: Extrai o identificados do sensor do chirpstack
        device_info = data.get("deviceInfo",{})
        dev_eui = device_info.get("devEui") or data.get("devEui")
        device_name = device_info.get("devicename", "Sensor_Galpao_lab")
        time_str = data.get("time")
        obj = data.get("object", {})

        if not dev_eui or not obj:
            return JsonResponse({"error": "Payload sem devEui ou dados dos sensores"}, status = 400)

        #Passo numnero 2: Registra o Local do nó sensor

        sensor, _ = SensorNode.objects.get_or_create(
            dev_eui = dev_eui,
            defaults = {"nome": device_name}
        )

        #Passo numero 3: Salva a nova Leitura (ignora se faltarem dados)
        co = obj.get("CO_MQ135")
        if co is None:
            return JsonResponse({"error": "Payload sem dados essenciais"}, status=400)
            
        AirReading.objects.create(
            sensor=sensor,
            timestamp=time_str,
            co_mq135=float(co),
            co2_mq135=float(obj.get("CO2_MQ135", 0.0)),
            mh4_mq135=float(obj.get("MH4_MQ135", 0.0)),
            aceton_mq135=float(obj.get("Aceton_MQ135", 0.0)),
            alcool_mq135=float(obj.get("Alcool_MQ135", 0.0)),
            toluen_mq135=float(obj.get("Toluen_MQ135", 0.0)),
            o3_mq131=float(obj.get("O3_MQ131", 0.0))
        )

        #Passo numero 4: Aciona o Agente Inteligente com as ultimas leituras (janela de 30 + confirmação)
        ultimas_leituras = list(AirReading.objects.filter(sensor=sensor).order_by('-timestamp')[:40])
        agente = AirQualifyService()
        resultado = agente.avaliar_janela(sensor, ultimas_leituras)

        if resultado:
            AgentPrediction.objects.create(
                sensor=sensor,
                anomalia=resultado["anomalia"],
                erro_reconstrucao=resultado["erro_reconstrucao"],
                classe_iqar=resultado["classe"],
                previsao_co=resultado["previsao"].get("CO_MQ135")
            )
            
            alerta = resultado.get("alerta")
            if alerta:
                AgentAlert.objects.create(
                    sensor=sensor,
                    tipo=alerta["tipo"],
                    mensagem=alerta["mensagem"]
                )
        return JsonResponse({"status": "sucesso", "sensor": dev_eui}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)