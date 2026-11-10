from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class RegistroImutavelError(Exception):
    """Tentativa de alterar ou apagar uma avaliação já registrada."""


class ImutavelQuerySet(models.QuerySet):
    """Fecha também as portas de atualização/exclusão em massa.

    Sem isto, ``Avaliacao.objects.filter(...).update(peso_kg=...)`` passaria
    por cima do ``save()`` bloqueado e sobrescreveria o histórico.
    """

    def update(self, **kwargs):
        raise RegistroImutavelError(
            'Avaliações são imutáveis: registre uma nova avaliação de correção.'
        )

    def delete(self):
        raise RegistroImutavelError('Avaliações não podem ser excluídas.')


class _Imutavel(models.Model):
    """Base: só permite INSERT. Depois de gravado, o registro não muda."""

    objects = ImutavelQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroImutavelError(
                'Avaliações são imutáveis: registre uma nova avaliação de correção.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroImutavelError('Avaliações não podem ser excluídas.')


MEDIDAS_CORPORAIS = [
    'torax_cm', 'cintura_cm', 'quadril_cm', 'braco_cm', 'coxa_cm', 'panturrilha_cm',
]


class AvaliacaoFisica(_Imutavel):
    """Uma avaliação física do aluno, numa data, feita por um professor.

    Cada avaliação é um registro novo — nunca uma atualização do anterior.
    A sequência delas é a evolução do aluno. Se uma avaliação foi lançada
    errada, a correção entra como OUTRO registro apontando para ela
    (``corrige``) e com o ``motivo_correcao``; o original permanece intacto.
    """

    aluno = models.ForeignKey(
        'alunos.Aluno',
        on_delete=models.PROTECT,
        related_name='avaliacoes_fisicas',
    )
    professor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='avaliacoes_registradas',
    )
    data_avaliacao = models.DateField(
        default=timezone.localdate,
        verbose_name='Data da avaliação',
    )
    registrada_em = models.DateTimeField(auto_now_add=True)

    peso_kg = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('20')), MaxValueValidator(Decimal('500'))],
        verbose_name='Peso (kg)',
    )
    altura_cm = models.DecimalField(
        max_digits=4, decimal_places=1,
        validators=[MinValueValidator(Decimal('50')), MaxValueValidator(Decimal('250'))],
        verbose_name='Altura (cm)',
    )
    percentual_gordura = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        verbose_name='Percentual de gordura (%)',
    )

    # Medidas corporais (cm)
    torax_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Tórax (cm)',
    )
    cintura_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Cintura (cm)',
    )
    quadril_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Quadril (cm)',
    )
    braco_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Braço (cm)',
    )
    coxa_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Coxa (cm)',
    )
    panturrilha_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('300'))],
        verbose_name='Panturrilha (cm)',
    )

    observacoes = models.TextField(blank=True, verbose_name='Observações')

    # Correção: esta avaliação substitui (sem apagar) a avaliação `corrige`.
    corrige = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='correcoes',
        verbose_name='Avaliação corrigida',
    )
    motivo_correcao = models.TextField(blank=True, verbose_name='Motivo da correção')

    class Meta:
        ordering = ['-data_avaliacao', '-registrada_em', '-pk']
        verbose_name = 'Avaliação física'
        verbose_name_plural = 'Avaliações físicas'
        constraints = [
            # Uma avaliação só pode ser corrigida uma vez; novas correções
            # apontam para a correção mais recente, formando uma cadeia
            # (sem bifurcar o histórico).
            models.UniqueConstraint(
                fields=['corrige'],
                condition=models.Q(corrige__isnull=False),
                name='uq_avaliacao_corrigida_uma_vez',
            ),
        ]

    # --- Campos calculados --------------------------------------------------

    @property
    def imc(self):
        """IMC = peso / altura². Sempre calculado, nunca digitado nem gravado."""
        altura_m = self.altura_cm / Decimal('100')
        return (self.peso_kg / (altura_m * altura_m)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    @property
    def medidas_preenchidas(self):
        """[(rótulo, valor)] só das medidas corporais que foram aferidas."""
        return [
            (self._meta.get_field(campo).verbose_name, getattr(self, campo))
            for campo in MEDIDAS_CORPORAIS
            if getattr(self, campo) is not None
        ]

    @property
    def substituida_por(self):
        """A avaliação que corrigiu esta, ou None se ela ainda vale."""
        return next(iter(self.correcoes.all()), None)

    @property
    def vigente(self):
        return self.substituida_por is None

    # --- Regras -------------------------------------------------------------

    def clean(self):
        erros = {}
        if self.data_avaliacao and self.data_avaliacao > timezone.localdate():
            erros['data_avaliacao'] = 'A data da avaliação não pode estar no futuro.'

        if self.corrige_id:
            original = self.corrige
            if original.aluno_id != self.aluno_id:
                raise ValidationError('A correção deve ser do mesmo aluno da avaliação original.')
            if not (self.motivo_correcao or '').strip():
                erros['motivo_correcao'] = 'Informe o motivo da correção.'
            ja_corrigida = original.correcoes.all()
            if self.pk:
                ja_corrigida = ja_corrigida.exclude(pk=self.pk)
            if ja_corrigida.exists():
                raise ValidationError(
                    'Esta avaliação já foi corrigida. Corrija a versão mais recente.'
                )

        if erros:
            raise ValidationError(erros)

    def __str__(self):
        return f'Avaliação de {self.aluno.nome} em {self.data_avaliacao:%d/%m/%Y}'


class TesteFisico(_Imutavel):
    """Resultado de um teste físico (ex.: flexões em 1 min, 12 min de corrida)."""

    avaliacao = models.ForeignKey(
        AvaliacaoFisica,
        on_delete=models.CASCADE,
        related_name='testes',
    )
    nome = models.CharField(max_length=100, verbose_name='Teste')
    resultado = models.DecimalField(
        max_digits=8, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Resultado',
    )
    unidade = models.CharField(max_length=20, blank=True, verbose_name='Unidade')

    class Meta:
        ordering = ['pk']
        verbose_name = 'Teste físico'
        verbose_name_plural = 'Testes físicos'

    def __str__(self):
        return f'{self.nome}: {self.resultado} {self.unidade}'.strip()