from django.contrib import admin
from .models import Plano, RegraFinanceira, HistoricoRegraFinanceira

@admin.register(Plano)
class PlanoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'periodicidade', 'valor', 'dia_vencimento', 'ativo')
    list_filter = ('ativo', 'periodicidade')
    search_fields = ('nome',)

@admin.register(RegraFinanceira)
class RegraFinanceiraAdmin(admin.ModelAdmin):
    list_display = ('dias_tolerancia', 'juros_diario', 'multa_atraso', 'dias_bloqueio', 'atualizado_por', 'atualizado_em')

    # as regras são editadas pela tela do financeiro (pra gerar histórico)
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(HistoricoRegraFinanceira)
class HistoricoRegraFinanceiraAdmin(admin.ModelAdmin):
    list_display = ('alterado_em', 'alterado_por_nome', 'campo', 'valor_anterior', 'valor_novo')
    list_filter = ('campo',)

    # o histórico é só leitura
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
