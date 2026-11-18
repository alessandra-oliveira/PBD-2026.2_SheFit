from django.urls import path

from . import views

urlpatterns = [
    path('', views.listar_fichas, name='listar_fichas'),
    path('nova/', views.criar_ficha, name='criar_ficha'),
    path('minha-ficha/', views.ficha_ativa_aluno, name='ficha_ativa_aluno'),
    path('<int:ficha_id>/', views.detalhe_ficha, name='detalhe_ficha'),
    path('minha-ficha/registrar/', views.registrar_execucao_aluno, name='registrar_execucao_aluno'),
    path('minha-ficha/evolucao/', views.evolucao_aluno, name='evolucao_aluno'),
    path('aluno/<int:aluno_id>/execucoes/', views.execucoes_aluno, name='execucoes_aluno'),
]
