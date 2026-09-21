from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from django.conf import settings

class Plano(models.Model):
    PERIODICIDADE_CHOICES = [
        ('mensal', 'Mensal'),
        ('trimestral', 'Trimestral'),
        ('semestral', 'Semestral'),
        ('anual', 'Anual'),
    ]

    nome = models.CharField(max_length=100, verbose_name="Nome do Plano")
    descricao = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Descrição do Plano",
        help_text="Resumo ou condições gerais do plano."
    )
    modalidades_incluidas = models.TextField(
        verbose_name="Modalidades Incluídas",
        help_text="Ex: Musculação, Dança, Pilates"
    )
    periodicidade = models.CharField(
        max_length=20, 
        choices=PERIODICIDADE_CHOICES, 
        default='mensal',
        verbose_name="Periodicidade"
    )
    valor = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Valor da Mensalidade (R$)"
    )
    fidelidade_meses = models.PositiveIntegerField(
        default=0, 
        verbose_name="Período de Fidelidade (meses)",
        help_text="0 se não houver fidelidade"
    )
    multa_cancelamento = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'),
        verbose_name="Multa por Cancelamento Antecipado (%)"
    )
    taxa_adesao = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Taxa de Adesão (R$)"
    )
    dia_vencimento = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        verbose_name="Dia Padrão de Vencimento"
    )
    ativo = models.BooleanField(
        default=True, 
        verbose_name="Plano Ativo?",
        help_text="Desmarque para ocultar este plano de novas matrículas."
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.get_periodicidade_display()}) - R$ {self.valor}"

class RegraFinanceira(models.Model):
    dias_tolerancia = models.PositiveIntegerField(
        verbose_name="Dias de tolerância",
        help_text="Dias após o vencimento antes de considerar o aluno inadimplente.",
        validators=[MaxValueValidator(365)],
    )
    juros_diario = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        verbose_name="Juros por dia de atraso (%)",
        help_text="Percentual cobrado por cada dia de atraso. Ex: 0,033",
        validators=[MinValueValidator(Decimal('0.000')), MaxValueValidator(Decimal('100'))],
    )
    multa_atraso = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="Multa por atraso (%)",
        help_text="Percentual único cobrado quando o pagamento atrasa. Ex: 2,00",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100'))],
    )
    dias_bloqueio = models.PositiveIntegerField(
        verbose_name="Dias de atraso que bloqueiam o acesso",
        help_text="A partir de quantos dias de atraso a entrada do aluno é bloqueada.",
        validators=[MaxValueValidator(365)],
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    # valores iniciais, usados só na primeira vez, pra nunca ter campo em branco
    PADRAO = {
        'dias_tolerancia': 3,
        'juros_diario': Decimal('0.033'),
        'multa_atraso': Decimal('2.00'),
        'dias_bloqueio': 15,
    }

    class Meta:
        verbose_name = "Regra financeira"
        verbose_name_plural = "Regras financeiras"

    def __str__(self):
        return (
            f"Tolerância {self.dias_tolerancia}d | juros {self.juros_diario}%/dia | "
            f"multa {self.multa_atraso}% | bloqueio {self.dias_bloqueio}d"
        )

    def save(self, *args, **kwargs):
        self.pk = 1 
        super().save(*args, **kwargs)

    @classmethod
    def obter(cls):
        """Devolve as regras vigentes (cria com os valores padrão se ainda não existirem)."""
        regras, _ = cls.objects.get_or_create(pk=1, defaults=cls.PADRAO)
        return regras


class HistoricoRegraFinanceira(models.Model):
    CAMPOS = [
        ('dias_tolerancia', 'Dias de tolerância'),
        ('juros_diario', 'Juros por dia de atraso (%)'),
        ('multa_atraso', 'Multa por atraso (%)'),
        ('dias_bloqueio', 'Dias de atraso que bloqueiam o acesso'),
    ]

    campo = models.CharField(max_length=30, choices=CAMPOS)
    valor_anterior = models.CharField(max_length=20)
    valor_novo = models.CharField(max_length=20)
    alterado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    # guarda o nome também, pro registro continuar legível se o usuário for apagado
    alterado_por_nome = models.CharField(max_length=150)
    alterado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Histórico de regra financeira"
        verbose_name_plural = "Histórico das regras financeiras"
        ordering = ['-alterado_em', '-id']

    def __str__(self):
        return f"{self.get_campo_display()}: {self.valor_anterior} -> {self.valor_novo} ({self.alterado_por_nome})"