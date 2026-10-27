from django.db import models


class ConfiguracaoRetreino(models.Model):
    ativo = models.BooleanField(
        default=True,
        verbose_name="Retreinamento Automático Ativo?",
        help_text="Marque ou desmarque para ligar ou desligar o retreino periódico."
    )
    intervalo_horas = models.PositiveIntegerField(
        default=48,
        verbose_name="Intervalo de Retreino (Horas)",
        help_text="Tempo em horas entre cada ciclo de aprendizado."
    )
    usar_ntp = models.BooleanField(
        default=True,
        verbose_name="Sincronizar Hora com Servidor NTP?",
        help_text="Garante auditoria temporal precisa com relógios oficiais."
    )
    servidor_ntp = models.CharField(
        max_length=100,
        default="a.st1.ntp.br",
        verbose_name="Servidor NTP de Referência",
        help_text="Ex: a.st1.ntp.br (NTP.br / Observatório Nacional) ou pool.ntp.org"
    )
    acuracia_minima_gatekeeper = models.FloatField(
        default=0.90,
        verbose_name="Acurácia Mínima para Promoção (0.0 a 1.0)",
        help_text="O modelo só será promovido se a acurácia no retreino for maior ou igual a este valor."
    )
    ultimo_retreino_sucesso = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Data/Hora do Último Retreino Bem-Sucedido"
    )

    class Meta:
        verbose_name = "Configuração de Retreino do Agente"
        verbose_name_plural = "Configurações de Retreino do Agente"

    def __str__(self):
        status = "ATIVADO" if self.ativo else "DESATIVADO"
        return f"Retreino Inteligente: {status} (A cada {self.intervalo_horas}h)"
