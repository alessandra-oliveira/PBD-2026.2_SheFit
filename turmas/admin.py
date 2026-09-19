from django.contrib import admin

from turmas.models import Turma, Modalidade


@admin.register(Modalidade)
class ModalidadeAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)

@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ('modalidade','dia_semana','horario','professor','sala','capacidade_maxima','ativo')
    list_filter = ('modalidade','dia_semana','ativo')
    search_fields = ('professor__username','sala')
