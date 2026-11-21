from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_financeiro, name='financeiro_home'),
    path('dashboard/', views.dashboard_financeiro, name='dashboard_financeiro'),
    path('planos/', views.listar_planos, name='listar_planos'),
    path('planos/cadastrar/', views.cadastrar_plano, name='cadastrar_plano'),
    path('planos/editar/<int:plano_id>/', views.editar_plano, name='editar_plano'),
    path('planos/alternar-status/<int:plano_id>/', views.alternar_status_plano, name='alternar_status_plano'),
    path('regras/', views.regras_financeiras, name='regras_financeiras'),
    path('relatorios/', views.relatorios_financeiros, name='relatorios_financeiros'),
    path(
        'relatorios/inadimplencia.csv',
        views.exportar_relatorio_inadimplencia,
        name='exportar_relatorio_inadimplencia',
    ),
]
