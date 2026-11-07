from django.contrib import admin
from .models import (
    Plano, RegraFinanceira, HistoricoRegraFinanceira, Matricula, Cobranca,
    Trancamento, Cancelamento,
)

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


class CobrancaInline(admin.TabularInline):
    """Cobranças aparecem dentro da matrícula, para criar/editar na mesma tela."""
    model = Cobranca
    extra = 0
    fields = ('tipo', 'valor', 'vencimento', 'competencia', 'paga')


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    inlines = [CobrancaInline]
    list_display = ('id', 'aluno', 'plano', 'data_inicio', 'situacao_display')
    # a situação é calculada: aparece aqui só para leitura, nunca como campo editável
    readonly_fields = ('situacao_display',)

    @admin.display(description='Situação')
    def situacao_display(self, obj):
        return obj.situacao_display


@admin.register(Trancamento)
class TrancamentoAdmin(admin.ModelAdmin):
    list_display = ('matricula', 'data_inicio', 'data_fim')


@admin.register(Cancelamento)
class CancelamentoAdmin(admin.ModelAdmin):
    list_display = ('matricula', 'data', 'motivo')