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
    telefone = models.CharField(max_length=11, unique=True, validators=[validador_telefone])
    email = models.EmailField(unique=True)
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

    @property
    def status_matricula(self):
        """Retorna o status real da matrícula baseado na anamnese."""
        if not hasattr(self, 'anamnese'):
            return "Pendente de Anamnese"
        if not self.anamnese.autorizacao_atividade_fisica:
            return "Bloqueado (Sem autorização médica)"
        if not self.ativo:
            return "Desativado"
        return "Ativo"

    @property
    def apto_para_treino(self):
        """Retorna True apenas se tiver anamnese e autorização confirmadas."""
        return (
            hasattr(self, 'anamnese') 
            and self.anamnese.autorizacao_atividade_fisica 
            and self.ativo
        )

class Anamnese(models.Model):
    aluno = models.OneToOneField(
        Aluno,
        on_delete=models.CASCADE,
        related_name='anamnese',
        verbose_name="Aluno"
    )

    restricoes_medicas = models.TextField(
        blank=True,
        null=True,
        verbose_name="Restrições Médicas",
        help_text="Problemas cardíacos, respiratórios, restrições articulares, etc."
    )
    historico_lesoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Histórico de Lesões",
        help_text="Fraturas, luxações, entorses, cirurgias ortopédicas prévias."
    )
    condicoes_cronicas = models.TextField(
        blank=True,
        null=True,
        verbose_name="Condições Crônicas",
        help_text="Hipertensão, diabetes, asma ou uso contínuo de medicação."
    )
    autorizacao_atividade_fisica = models.BooleanField(
        default=False,
        verbose_name="Autorização para prática de atividade física",
        help_text="Declaração de aptidão e autorização para os treinos na academia."
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Anamnese"
        verbose_name_plural = "Anamneses"

    def __str__(self):
        status = "Autorizado" if self.autorizacao_atividade_fisica else "Não autorizado"
        return f"Anamnese de {self.aluno.nome} - {status}"