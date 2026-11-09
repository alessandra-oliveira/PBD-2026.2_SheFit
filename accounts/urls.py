from django.urls import path
from . import views

urlpatterns = [
    path('entrar/', views.entrar, name='entrar'),
    path('painel/recepcao/', views.painel_recepcao, name='painel_recepcao'),
    path('sair/', views.sair, name='sair'),
    path('painel/estudantes/', views.gestao_estudantes_view, name='gestao_estudantes'),
]
