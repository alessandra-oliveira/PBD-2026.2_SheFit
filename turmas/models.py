from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User


class Modalidade(models.Model):
    nome = models.CharField(max_length=100,unique=True)
    descricao = models.TextField(blank=True)

    def __str__(self):
        return self.nome



class Turma(models.Model):
    SEGUNDA = "segunda"
    TERCA = "terca"
    QUARTA = "quarta"
    QUINTA = "quinta"
    SEXTA = "sexta"
    SABADO = "sabado"
    DOMINGO = "domingo"

    DIAS_SEMANA = [
        (SEGUNDA, "Segunda"),
        (TERCA, "Terça"),
        (QUARTA, "Quarta"),
        (QUINTA, "Quinta"),
        (SEXTA, "Sexta"),
        (SABADO, "Sabado"),
        (DOMINGO, "Domingo"),
    ]

    modalidade = models.ForeignKey(Modalidade, on_delete=models.PROTECT, related_name='turmas')
    dia_semana = models.CharField(max_length=7, choices=DIAS_SEMANA)
    horario = models.TimeField()

    professor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='turmas_lecionadas',
        limit_choices_to={'perfil__tipo':'professor'}

    )

    sala = models.CharField(max_length=50)
    capacidade_maxima = models.PositiveBigIntegerField()

    ativo= models.BooleanField(default=True)

    def clean(self):
        if self.capacidade_maxima is not None and self.capacidade_maxima <= 0:
            raise ValidationError({
                'capacidade_maxima' : 'A capacidade deve ser maior que zero.',
            })

    def vagas_restantes(self):
        """Capacidade menos as vagas já reservadas (quem está na lista de espera não conta)."""
        ocupadas = self.agendamentos.filter(status='reservado').count()
        return max(self.capacidade_maxima - ocupadas, 0)

    def tem_aluno_agendado(self):
        """True se há alguém com vaga reservada ou esperando. Turma assim só pode ser desativada."""
        return self.agendamentos.filter(status__in=['reservado', 'espera']).exists()

    def ocupacao_real_na_data(self, data_aula):
        """Retorna quantos alunos realmente compareceram na data específica."""
        return self.frequencias.filter(data=data_aula, presente=True).count()

    def __str__(self):
        return f'{self.modalidade.nome}\n{self.get_dia_semana_display()} {self.horario}'

    class Meta:
        verbose_name_plural = 'Turmas'


class Frequencia(models.Model):
    turma = models.ForeignKey(Turma, on_delete=models.CASCADE, related_name='frequencias')
    aluno = models.ForeignKey(User, on_delete=models.CASCADE, related_name='frequencias_aluno')
    data = models.DateField()
    presente = models.BooleanField(default=False)
    
    # Auditoria de correção exigida pela Task T12 (caso seja alterado por engano)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='frequencias_modificadas'
    )

    class Meta:
        unique_together = ('turma', 'aluno', 'data')  # Garante um registro por aluno/turma/dia
        verbose_name = 'Frequência'
        verbose_name_plural = 'Frequências'

    def __str__(self):
        status = "Presente" if self.presente else "Falta"
        return f"{self.aluno.get_full_name()} - Turma ID {self.turma.id} ({self.data}): {status}"