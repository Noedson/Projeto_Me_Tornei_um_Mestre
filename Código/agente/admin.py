from django.contrib import admin
from .models import ConfiguracaoRetreino


@admin.register(ConfiguracaoRetreino)
class ConfiguracaoRetreinoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ativo",
        "intervalo_horas",
        "usar_ntp",
        "servidor_ntp",
        "acuracia_minima_gatekeeper",
        "ultimo_retreino_sucesso",
    )
    list_display_links = ("id",)
    list_editable = ("ativo", "intervalo_horas", "usar_ntp", "acuracia_minima_gatekeeper")

    def has_add_permission(self, request):
        # Permite adicionar apenas se ainda não existir nenhuma linha
        return not ConfiguracaoRetreino.objects.exists()
