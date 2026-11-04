from django.contrib import admin
from .models import SensorNode, AirReading, AgentAlert, AgentPrediction
# Register your models here.

@admin.register(SensorNode)
class SensorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'dev_eui', 'localizacao', 'criado_em')

@admin.register(AirReading)
class AirReadingAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'timestamp', 'co_mq135', 'co2_mq135', 'o3_mq131')
    list_filter = ('sensor', 'timestamp')

@admin.register(AgentAlert)
class AgenteAlertAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'tipo', 'timestamp', 'resolvido')
    list_filter = ('tipo', 'resolvido')

@admin.register(AgentPrediction)
class AgentPredictionAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'timestamp', 'classe_iqar', 'anomalia', 'erro_reconstrucao', 'previsao_co')
    list_filter = ('classe_iqar', 'anomalia', 'sensor')
    search_fields = ('sensor__nome',)