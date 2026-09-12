from django.contrib import admin
from .models import Aluno


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cpf', 'telefone', 'email', 'ativo', 'criado_em')
    list_filter = ('ativo',)
    search_fields = ('nome', 'cpf', 'email')
    readonly_fields = ('criado_em', 'atualizado_em')

    # Como o model bloqueia delete() físico, desativa a ação de exclusão em massa
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False