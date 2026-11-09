from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class FichaTreino(models.Model):
    aluno = models.ForeignKey(
        'alunos.Aluno',
        on_delete=models.PROTECT,
        related_name='fichas_treino',
    )
    professor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='fichas_treino_criadas',
    )
    criada_em = models.DateTimeField(auto_now_add=True)
    data_revisao = models.DateField(verbose_name='Data prevista para revisão')
    ativa = models.BooleanField(default=True)
    encerrada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criada_em', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['aluno'],
                condition=models.Q(ativa=True),
                name='uq_ficha_treino_ativa_por_aluno',
            ),
        ]
        verbose_name = 'Ficha de treino'
        verbose_name_plural = 'Fichas de treino'

    def encerrar(self):
        self.ativa = False
        self.encerrada_em = timezone.now()
        self.save(update_fields=['ativa', 'encerrada_em'])

    def __str__(self):
        return f'Ficha de treino de {self.aluno.nome} ({self.criada_em:%d/%m/%Y})'


class ExercicioTreino(models.Model):
    ficha = models.ForeignKey(
        FichaTreino,
        on_delete=models.CASCADE,
        related_name='exercicios',
    )
    nome = models.CharField(max_length=150, verbose_name='Exercício')
    series = models.PositiveIntegerField(null=True, blank=True, verbose_name='Séries')
    repeticoes = models.PositiveIntegerField(null=True, blank=True, verbose_name='Repetições')
    carga_sugerida = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Carga sugerida',
    )
    observacoes = models.TextField(blank=True, verbose_name='Observações')

    class Meta:
        ordering = ['pk']
        verbose_name = 'Exercício da ficha'
        verbose_name_plural = 'Exercícios da ficha'

    def __str__(self):
        return self.nome
