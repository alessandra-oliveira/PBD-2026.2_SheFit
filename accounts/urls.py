from django.urls import path
from . import views

urlpatterns = [
    path('entrar/', views.entrar, name='entrar'),
    path('sair/', views.sair, name='sair'),
    path('painel/admin/', views.painel_admin, name='painel_admin'),
    path('painel/admin/usuarios/<int:user_id>/alternar-status/', views.alternar_status_usuario, name='alternar_status_usuario'),
    path('painel/recepcao/', views.painel_recepcao, name='painel_recepcao'),
    path('painel/estudantes/', views.gestao_estudantes_view, name='gestao_estudantes'),
]

