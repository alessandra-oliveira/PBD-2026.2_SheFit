from django.urls import path

from . import views

urlpatterns = [
    path('', views.minhas_aulas, name='minhas_aulas'),
    path('turmas/<int:turma_id>/agendar/', views.agendar_turma, name='agendar_turma'),
    path('<int:agendamento_id>/cancelar/', views.cancelar, name='cancelar_agendamento'),
]