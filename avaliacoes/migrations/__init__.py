import decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("alunos", "0007_delete_frequencia"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AvaliacaoFisica",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "data_avaliacao",
                    models.DateField(
                        default=django.utils.timezone.localdate,
                        verbose_name="Data da avaliação",
                    ),
                ),
                ("registrada_em", models.DateTimeField(auto_now_add=True)),
                (
                    "peso_kg",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("20")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("500")),
                        ],
                        verbose_name="Peso (kg)",
                    ),
                ),
                (
                    "altura_cm",
                    models.DecimalField(
                        decimal_places=1,
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("50")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("250")),
                        ],
                        verbose_name="Altura (cm)",
                    ),
                ),
                (
                    "percentual_gordura",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("0")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("100")),
                        ],
                        verbose_name="Percentual de gordura (%)",
                    ),
                ),
                (
                    "torax_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Tórax (cm)",
                    ),
                ),
                (
                    "cintura_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Cintura (cm)",
                    ),
                ),
                (
                    "quadril_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Quadril (cm)",
                    ),
                ),
                (
                    "braco_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Braço (cm)",
                    ),
                ),
                (
                    "coxa_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Coxa (cm)",
                    ),
                ),
                (
                    "panturrilha_cm",
                    models.DecimalField(
                        blank=True, null=True, decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("1")),
                            django.core.validators.MaxValueValidator(decimal.Decimal("300")),
                        ],
                        verbose_name="Panturrilha (cm)",
                    ),
                ),
                (
                    "observacoes",
                    models.TextField(blank=True, verbose_name="Observações"),
                ),
                (
                    "motivo_correcao",
                    models.TextField(blank=True, verbose_name="Motivo da correção"),
                ),
                (
                    "aluno",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="avaliacoes_fisicas",
                        to="alunos.aluno",
                    ),
                ),
                (
                    "corrige",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="correcoes",
                        to="avaliacoes.avaliacaofisica",
                        verbose_name="Avaliação corrigida",
                    ),
                ),
                (
                    "professor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="avaliacoes_registradas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Avaliação física",
                "verbose_name_plural": "Avaliações físicas",
                "ordering": ["-data_avaliacao", "-registrada_em", "-pk"],
            },
        ),
        migrations.CreateModel(
            name="TesteFisico",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nome", models.CharField(max_length=100, verbose_name="Teste")),
                (
                    "resultado",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=8,
                        validators=[
                            django.core.validators.MinValueValidator(decimal.Decimal("0"))
                        ],
                        verbose_name="Resultado",
                    ),
                ),
                (
                    "unidade",
                    models.CharField(blank=True, max_length=20, verbose_name="Unidade"),
                ),
                (
                    "avaliacao",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="testes",
                        to="avaliacoes.avaliacaofisica",
                    ),
                ),
            ],
            options={
                "verbose_name": "Teste físico",
                "verbose_name_plural": "Testes físicos",
                "ordering": ["pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="avaliacaofisica",
            constraint=models.UniqueConstraint(
                condition=models.Q(("corrige__isnull", False)),
                fields=("corrige",),
                name="uq_avaliacao_corrigida_uma_vez",
            ),
        ),
    ]