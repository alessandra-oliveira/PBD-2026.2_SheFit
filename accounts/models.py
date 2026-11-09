from django.db import models
from django.contrib.auth.models import User


class Perfil(models.Model):
    class Tipo(models.TextChoices):
        ADMIN = 'admin', 'Administrador'
        RECEPCAO = 'recepcao', 'Recepção'
        PROFESSOR = 'professor', 'Professor'
        FINANCEIRO = 'financeiro', 'Financeiro'
        ALUNO = 'aluno', 'Aluno'

    # Constantes mantidas para retrocompatibilidade em todo o projeto
    ADMIN = Tipo.ADMIN
    RECEPCAO = Tipo.RECEPCAO
    FINANCEIRO = Tipo.FINANCEIRO
    PROFESSOR = Tipo.PROFESSOR
    ALUNO = Tipo.ALUNO

    OPCOES_PERFIL = Tipo.choices

    # Conecta perfil ao user
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')

    # Guarda qual é o perfil
    tipo = models.CharField(max_length=20, choices=Tipo.choices)

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfis'

    def __str__(self):
        return f'{self.usuario.username} ({self.get_tipo_display()})'

    @property
    def is_admin(self):
        return self.tipo == self.Tipo.ADMIN

    @property
    def is_recepcao(self):
        return self.tipo == self.Tipo.RECEPCAO

    @property
    def is_professor(self):
        return self.tipo == self.Tipo.PROFESSOR

    @property
    def is_financeiro(self):
        return self.tipo == self.Tipo.FINANCEIRO

    @property
    def is_aluno(self):
        return self.tipo == self.Tipo.ALUNO




