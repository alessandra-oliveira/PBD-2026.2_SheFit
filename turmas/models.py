

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

    def __str__(self):
        return f'{self.modalidade.nome} - {self.get_dia_semana_display()} {self.horario}'

    class Meta:
        verbose_name_plural = 'Turmas'

