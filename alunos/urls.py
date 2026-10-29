from django.urls import path
from . import views

urlpatterns = [
    path('cadastrar/', views.cadastrar_aluno, name='cadastrar_aluno'),
    path('<int:aluno_id>/anamnese/', views.preencher_anamnese, name='preencher_anamnese'),
    path('<int:aluno_id>/anamnese/consulta/', views.consultar_anamnese, name='consultar_anamnese'),
    path('editar/<int:aluno_id>/', views.editar_aluno, name='editar_aluno'),
    path('matriculas/nova/', views.criar_matricula, name='criar_matricula'),
    path('api/estudantes/salvar/', views.api_salvar_aluno, name='api_salvar_aluno'),
    path('api/estudantes/', views.api_listar_alunos, name='api_estudantes'),
]