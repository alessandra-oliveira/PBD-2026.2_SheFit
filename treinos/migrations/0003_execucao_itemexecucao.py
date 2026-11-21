

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alunos", "0007_delete_frequencia"),
        ("treinos", "0002_execucaoexercicio"),
    ]

    operations = [
        migrations.CreateModel(
            name="Execucao",
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
                    "data",
                    models.DateField(
                        default=django.utils.timezone.localdate,
                        verbose_name="Data do treino",
                    ),
                ),
                ("registrada_em", models.DateTimeField(auto_now_add=True)),
                (
                    "observacoes",
                    models.TextField(blank=True, verbose_name="Observações"),
                ),
                (
                    "total_prescritos",
                    models.PositiveIntegerField(
                        verbose_name="Exercícios prescritos na ficha"
                    ),
                ),
                (
                    "aluno",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execucoes_treino",
                        to="alunos.aluno",
                    ),
                ),
                (
                    "ficha",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execucoes",
                        to="treinos.fichatreino",
                    ),
                ),
            ],
            options={
                "verbose_name": "Execução de treino",
                "verbose_name_plural": "Execuções de treino",
                "ordering": ["-data", "-pk"],
            },
        ),
        migrations.CreateModel(
            name="ItemExecucao",
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
                ("nome", models.CharField(max_length=150, verbose_name="Exercício")),
                (
                    "carga_prescrita",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=8,
                        null=True,
                        verbose_name="Carga prescrita",
                    ),
                ),
                (
                    "carga_efetiva",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=8,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Carga efetiva",
                    ),
                ),
                (
                    "execucao",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="itens",
                        to="treinos.execucao",
                    ),
                ),
                (
                    "exercicio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="itens_execucao",
                        to="treinos.exerciciotreino",
                    ),
                ),
            ],
            options={
                "verbose_name": "Item da execução",
                "verbose_name_plural": "Itens da execução",
                "ordering": ["pk"],
            },
        ),
    ]
