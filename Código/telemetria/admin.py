from django.contrib import admin
from .models import SensorNode, AirReading, AgentAlert
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
    list_alert = ('tipo', 'resolido')