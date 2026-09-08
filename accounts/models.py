from django.db import models
from django.contrib.auth.models import  User

class Perfil(models.Model):
    RECEPCAO = 'recepcao'
    FINANCEIRO = 'financeiro'
    PROFESSOR = 'professor'
    ALUNO = 'aluno'

    OPCOES_PERFIL = [
        (RECEPCAO, 'Recepcao'),
        (FINANCEIRO, 'Financeiro'),
        (PROFESSOR, 'Professor'),
        (ALUNO, 'Aluno'),
    ]
    #conecta perfil ao user
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')

    #guarda qual é o perfil
    tipo = models.CharField(max_length=20, choices=OPCOES_PERFIL)

    def __str__(self):
        return f'{self.usuario.username} ({self.get_tipo_display()})'



