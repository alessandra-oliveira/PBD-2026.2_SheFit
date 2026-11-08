from django.contrib import admin

from .models import Agendamento


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    """Somente leitura: mexer no status por aqui pularia a trava da turma e a promoção
    da lista de espera. Reservas e cancelamentos acontecem pelas telas do aluno."""
    list_display = ('id', 'aluno', 'turma', 'status', 'criado_em', 'promovido_em', 'cancelado_em')
    list_filter = ('status', 'turma')
    search_fields = ('aluno__nome', 'aluno__cpf')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False