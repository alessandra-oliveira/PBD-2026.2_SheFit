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






class RegistroImutavelError(Exception):
    """Execuções registradas não podem ser alteradas nem apagadas."""


class ImutavelQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RegistroImutavelError('Execuções registradas não podem ser alteradas.')

    def delete(self):
        raise RegistroImutavelError('Execuções registradas não podem ser apagadas.')


class RegistroImutavel(models.Model):
    objects = ImutavelQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroImutavelError('Execuções registradas não podem ser alteradas.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroImutavelError('Execuções registradas não podem ser apagadas.')


class Execucao(RegistroImutavel):
    aluno = models.ForeignKey(
        'alunos.Aluno',
        on_delete=models.PROTECT,
        related_name='execucoes_treino',
    )
    ficha = models.ForeignKey(
        FichaTreino,
        on_delete=models.PROTECT,
        related_name='execucoes',
    )
    data = models.DateField(default=timezone.localdate, verbose_name='Data do treino')
    registrada_em = models.DateTimeField(auto_now_add=True)
    observacoes = models.TextField(blank=True, verbose_name='Observações')
    total_prescritos = models.PositiveIntegerField(
        verbose_name='Exercícios prescritos na ficha',
    )

    class Meta:
        ordering = ['-data', '-pk']
        verbose_name = 'Execução de treino'
        verbose_name_plural = 'Execuções de treino'

    def __str__(self):
        return f'Treino de {self.aluno.nome} em {self.data:%d/%m/%Y}'


class ItemExecucao(RegistroImutavel):
    execucao = models.ForeignKey(
        Execucao,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    exercicio = models.ForeignKey(
        ExercicioTreino,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_execucao',
    )
    nome = models.CharField(max_length=150, verbose_name='Exercício')
    carga_prescrita = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name='Carga prescrita',
    )
    carga_efetiva = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        verbose_name='Carga efetiva',
    )

    class Meta:
        ordering = ['pk']
        verbose_name = 'Item da execução'
        verbose_name_plural = 'Itens da execução'

    def __str__(self):
        return self.nome






class ExecucaoExercicio(models.Model):
    """O que a aluna realmente fez num exercício (≠ `carga_sugerida`, que é a prescrição)."""
    aluno = models.ForeignKey('alunos.Aluno', on_delete=models.PROTECT, related_name='execucoes_exercicio')
    exercicio = models.ForeignKey(ExercicioTreino, on_delete=models.PROTECT, related_name='execucoes')
    data = models.DateField(default=timezone.localdate, verbose_name='Data')
    carga_kg = models.DecimalField(max_digits=8, decimal_places=2,
                                   validators=[MinValueValidator(0)], verbose_name='Carga (kg)')
    series = models.PositiveIntegerField(null=True, blank=True, verbose_name='Séries')
    repeticoes = models.PositiveIntegerField(null=True, blank=True, verbose_name='Repetições')
    registrada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data', 'pk']
        verbose_name = 'Execução de exercício'
        verbose_name_plural = 'Execuções de exercício'

    def __str__(self):
        return f'{self.exercicio.nome}: {self.carga_kg} kg em {self.data:%d/%m/%Y}'
