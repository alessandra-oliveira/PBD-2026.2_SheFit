from django.contrib import admin
from .models import Perfil


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo')
    list_filter = ('tipo',)
    search_fields = ('usuario__username', 'usuario__email', 'usuario__first_name', 'usuario__last_name')
