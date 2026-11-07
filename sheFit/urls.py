from django.contrib import admin
from django.urls import include, path
from accounts.views import (
    entrar, sair, painel,
    painel_aluno, painel_professor, painel_recepcao, painel_financeiro,
    gestao_estudantes_view
)

urlpatterns = [
    # Rota raiz direcionando para o painel de acordo com o perfil
    path('', painel, name='home'),

    path('admin/', admin.site.urls),
    path('entrar/', entrar, name='entrar'),
    path('sair/', sair, name='sair'),
    path('alunos/', include('alunos.urls')),
    path('recepcao/', include('recepcao.urls')), 
    path('', include('turmas.urls')),
    path('financeiro/', include('financeiro.urls')),
    path('', include('accounts.urls')),

    # rotas dos painéis
    path('painel/', painel, name='painel'),
    path('painel/aluno/', painel_aluno, name='painel_aluno'),
    path('painel/professor/', painel_professor, name='painel_professor'),
    path('painel/recepcao/', painel_recepcao, name='painel_recepcao'),
    path('painel/financeiro/', painel_financeiro, name='painel_financeiro'),
    path('painel/estudantes/', gestao_estudantes_view, name='gestao_estudantes'),
]
