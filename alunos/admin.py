from django.contrib import admin
from .models import Aluno, Anamnese

class AnamneseInline(admin.StackedInline):
    model = Anamnese
    can_delete = False
    verbose_name_plural = 'Ficha de Anamnese'

@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cpf', 'telefone', 'get_status_matricula')
    list_filter = ('ativo',)
    search_fields = ('nome', 'cpf')
    inlines = [AnamneseInline]

    @admin.display(description='Status da Matrícula')
    def get_status_matricula(self, obj):
        return obj.status_matricula