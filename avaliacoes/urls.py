from django.urls import path

from . import views

urlpatterns = [
    # Aluno (rotas fixas primeiro)
    path('minha-evolucao/', views.minha_evolucao, name='minha_evolucao'),
    path('minha-evolucao/comparar/', views.minha_comparacao, name='minha_comparacao'),

    # Professor
    path('', views.listar_alunos, name='avaliacoes_alunos'),
    path('aluno/<int:aluno_id>/', views.evolucao_aluno, name='avaliacoes_aluno'),
    path('aluno/<int:aluno_id>/nova/', views.registrar_avaliacao, name='registrar_avaliacao'),
    path('aluno/<int:aluno_id>/comparar/', views.comparar_avaliacoes_aluno, name='comparar_avaliacoes_aluno'),
    path('<int:avaliacao_id>/corrigir/', views.corrigir_avaliacao, name='corrigir_avaliacao'),
]