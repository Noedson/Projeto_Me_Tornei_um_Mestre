
from django.db import models

# Create your models here.

class SensorNode(models.Model):
    dev_eui = models.CharField(max_length=31, unique=True, verbose_name="DevEUI")
    nome = models.CharField(max_length=100, default="Sensor_Galpao_lab")
    localizacao = models.CharField(max_length=150, blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome} ({self.dev_eui})"

class AirReading(models.Model):
    sensor = models.ForeignKey(SensorNode, on_delete = models.CASCADE, 
                               related_name = "leituras")
    
    timestamp = models.DateTimeField(db_index = True)

    # Gases extraido do JSON da colula 'Object' do chirpstack

    co_mq135 = models.FloatField(verbose_name= "CO (MQ - 135)")
    co2_mq135 = models.FloatField(verbose_name= "CO2 (MQ - 135)")
    mh4_mq135 = models.FloatField(verbose_name= "MH4 (MQ - 135)")
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
    sensor = models.ForeignKey(SensorNode, on_delete=models.CASCADE, related_name="alertas")
    timestamp = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensagem = models.TextField()
    resolvido = models.BooleanField(default=False)

    def __str__(self):
        return f"[{self.tipo}] {self.sensor.nome} - {self.timestamp}"

class AgentPrediction(models.Model):
    sensor = models.ForeignKey(SensorNode, on_delete=models.CASCADE, related_name="previsoes")
    timestamp = models.DateTimeField(auto_now_add=True)
    anomalia = models.BooleanField(default=False)
    erro_reconstrucao = models.FloatField()
    classe_iqar = models.CharField(max_length=30)
    previsao_co = models.FloatField(null=True, blank=True)
    
    def __str__(self):
        return f"Previsão {self.sensor.nome} em {self.timestamp}: {self.classe_iqar}"