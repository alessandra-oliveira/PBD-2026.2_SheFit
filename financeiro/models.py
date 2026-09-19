from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

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