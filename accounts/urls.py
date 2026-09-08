from django import urls
from django.urls import path
from . import views

urlpatterns = [
    path('entrar/', views.entrar, name='entrar'),

    path('sair/', views.sair, name='sair'),
]