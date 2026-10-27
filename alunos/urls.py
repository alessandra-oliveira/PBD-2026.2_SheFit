from django.urls import path
from . import views

urlpatterns = [
    path('cadastrar/', views.cadastrar_aluno, name='cadastrar_aluno'),
    path('<int:aluno_id>/anamnese/', views.preencher_anamnese, name='preencher_anamnese'),
    path('<int:aluno_id>/anamnese/consulta/', views.consultar_anamnese, name='consultar_anamnese'),
    path('editar/<int:aluno_id>/', views.editar_aluno, name='editar_aluno'),
    path('matriculas/nova/', views.criar_matricula, name='criar_matricula'),
    path('recepcao/entrada/', views.tela_entrada_recepcao, name='tela_entrada_recepcao'),
]