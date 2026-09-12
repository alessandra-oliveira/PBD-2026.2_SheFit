# alunos/models.py
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from accounts.models import Perfil


validador_cpf = RegexValidator(
    regex=r'^\d{11}$',
    message='CPF deve conter exatamente 11 números, sem pontos ou traços.'
)

validador_telefone = RegexValidator(
    regex=r'^\d{10,11}$',
    message='Telefone deve conter 10 ou 11 números (com DDD), sem espaços ou traços.'
)


class Aluno(models.Model):
    perfil = models.OneToOneField(
        Perfil,
        on_delete=models.CASCADE,
        related_name='aluno',
        limit_choices_to={'tipo': Perfil.ALUNO}
    )

    nome = models.CharField(max_length=150)
    cpf = models.CharField(max_length=11, unique=True, validators=[validador_cpf])
    data_nascimento = models.DateField()
    endereco = models.CharField(max_length=255)
    telefone = models.CharField(max_length=11, validators=[validador_telefone])
    email = models.EmailField()
    foto = models.ImageField(upload_to='alunos/fotos/', blank=True, null=True)

    contato_emergencia_nome = models.CharField(max_length=150)
    contato_emergencia_telefone = models.CharField(max_length=11, validators=[validador_telefone])

    ativo = models.BooleanField(default=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def clean(self):
        if Aluno.objects.exclude(pk=self.pk).filter(cpf=self.cpf).exists():
            raise ValidationError({'cpf': 'Já existe um aluno cadastrado com esse CPF.'})

    def desativar(self):
        self.ativo = False
        self.save()

    def delete(self, *args, **kwargs):
        raise NotImplementedError(
            "Alunos não podem ser excluídos, apenas desativados. Use o método desativar()."
        )

    def __str__(self):
        return f'{self.nome} ({self.cpf})'

    class Meta:
        ordering = ['nome']