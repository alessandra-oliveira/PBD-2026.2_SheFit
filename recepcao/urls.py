from django.urls import path
from . import views

urlpatterns = [
    path('entrada/', views.tela_entrada_recepcao, name='tela_entrada_recepcao'),
]