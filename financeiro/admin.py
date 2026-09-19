from django.contrib import admin
from .models import Plano

@admin.register(Plano)
class PlanoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'periodicidade', 'valor', 'dia_vencimento', 'ativo')
    list_filter = ('ativo', 'periodicidade')
    search_fields = ('nome',)
