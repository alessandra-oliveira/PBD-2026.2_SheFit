from django.contrib import admin

from .models import AvaliacaoFisica, TesteFisico


class TesteFisicoInline(admin.TabularInline):
    model = TesteFisico
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AvaliacaoFisica)
class AvaliacaoFisicaAdmin(admin.ModelAdmin):
    """Somente consulta: o histórico não se edita nem se apaga, nem pelo admin."""

    list_display = ('aluno', 'data_avaliacao', 'peso_kg', 'altura_cm', 'get_imc', 'professor', 'corrige')
    list_filter = ('data_avaliacao',)
    search_fields = ('aluno__nome', 'aluno__cpf')
    inlines = [TesteFisicoInline]

    @admin.display(description='IMC')
    def get_imc(self, obj):
        return obj.imc

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False