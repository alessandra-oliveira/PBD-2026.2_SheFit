import os
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve
from django.conf import settings
from accounts.views import (
    entrar, sair, painel,
    painel_aluno, painel_professor, painel_recepcao, painel_financeiro
)
from financeiro import views as financeiro_views  
from accounts import views as accounts_views
from turmas import views as turmas_views

urlpatterns = [
    # Rota raiz servindo a SPA React da Recepção
    path('', TemplateView.as_view(template_name='index.html'), name='home'),

    path('admin/', admin.site.urls),
    path('entrar/', entrar, name='entrar'),
    path('sair/', sair, name='sair'),
    path('alunos/', include('alunos.urls')),
    path('recepcao/', include('recepcao.urls')), 
    path('', include('turmas.urls')),
    path('financeiro/', include('financeiro.urls')),
    
    # APIs para o React
    path('api/usuario-atual/', accounts_views.api_usuario_atual, name='api_usuario_atual'),
    path('accounts/api/usuario-atual/', accounts_views.api_usuario_atual),
    path('api/sair/', accounts_views.api_sair, name='api_sair'),
    path('api/professores/listar/', accounts_views.api_listar_professores, name='api_listar_professores'),
    path('accounts/api/professores/listar/', accounts_views.api_listar_professores),
    path('api/modalidades/criar/', turmas_views.api_criar_modalidade, name='api_criar_modalidade'),
    path('api/turmas/criar/', turmas_views.api_criar_turma, name='api_criar_turma'),
    path('api/dashboard/recepcao/', accounts_views.api_dashboard_recepcao, name='api_dashboard_recepcao'),

    # rotas dos paineis
    path('painel/', painel, name='painel'),
    path('painel/aluno/', painel_aluno, name='painel_aluno'),
    path('painel/professor/', painel_professor, name='painel_professor'),
    path('painel/recepcao/', TemplateView.as_view(template_name='index.html'), name='painel_recepcao'),
    path('painel/financeiro/', painel_financeiro, name='painel_financeiro'),
]

# Servir arquivos estáticos do React no desenvolvimento e produção local
if settings.DEBUG:
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.REACT_DIST_DIR}),
        re_path(r'^assets/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.REACT_DIST_DIR, 'assets')}),
    ]
