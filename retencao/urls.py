from django.urls import path

from . import views

urlpatterns = [
    path('', views.numeros_da_academia, name='numeros_da_academia'),
]