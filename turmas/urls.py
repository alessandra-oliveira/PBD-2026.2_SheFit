from django.urls import path
from . import views

urlpatterns = [
    path('turmas/', views.listar_turmas, name='listar_turmas'),
    path('turmas/nova/', views.criar_turma, name='criar_turma'),
    path('turmas/<int:turma_id>/editar/', views.editar_turma, name='editar_turma'),
    path('turmas/<int:turma_id>/desativar/', views.desativar_turma, name='desativar_turma'),
    path('modalidades/nova/', views.criar_modalidade, name='criar_modalidade'),
]