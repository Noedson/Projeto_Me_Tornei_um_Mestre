import select
from django.utils import version
from django.db import models

# Create your models here.

class SensorNode(models.Model):
    dev_eui = models.CharField(max_length = 31, unique = True, verbose = "DevEUI")
    nome = models.CharField(max_lenght = 100, default = "Sensor_Galpao_lab")
    localizacao = models.CharField(maxLenght = 150, blank = True, null = True)

    def __str__(self):
        return f"{self.nome} ({self.dev_eui})"

class AirReading(models.Model):
    sensor = models.ForeignKey(SensorNode, on_delete = models.CASCADE, 
                               related_name = "leituras")
    
    timestamp = models.DateField(db_index = True)

    # Gases extraido do JSON da colula 'Object' do chirpstack

    co_mq135 = models.FloatField(verbose_name= "CO (MQ - 135)")
    co2_mq135 = models.FloatField(verbose_name= "CO2 (MQ - 135)")
    nh4_mq135 = models.FloatField(verbose_name= "NH4 (MQ - 135)")
    aceton_mq135 = models.FloatField(verbose_name= "Acetona (MQ - 135)")
    alcool_mq135 = models.FloatField(verbose_name= "Alcool (MQ - 135)")
    toluen_mq135 = models.FloatField(verbose_name= "Tolueno (MQ - 135)")

    o3_mq131 = models.FloatField(verbose_name= "O3 (MQ - 131)")

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Leitura {self.sensor.nome} em {self.timestamp}"

class AgentAlert(models.Model):
    TIPO_CHOICES = [
        ('ANOMALIA','Anomalia Detectada (Pico ou Falha)'),
        ('PREVISAO_CRITICA','Risco Futuro Previsto'),
    ]
    