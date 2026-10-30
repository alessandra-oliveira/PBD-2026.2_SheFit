from django import urls
from django.urls import path
from . import views

urlpatterns = [
    path('entrar/', views.entrar, name='entrar'),
    path('painel/', views.painel_recepcao, name='painel_recepcao'),
    path('sair/', views.sair, name='sair'),
]