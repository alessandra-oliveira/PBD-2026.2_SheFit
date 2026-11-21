

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("financeiro", "0010_plano_renovacao_automatica_renovacao"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="trancamento",
            options={
                "ordering": ["-data_inicio"],
                "verbose_name": "Trancamento",
                "verbose_name_plural": "Trancamentos",
            },
        ),
        migrations.RemoveField(
            model_name="cancelamento",
            name="cancelada",
        ),
        migrations.RemoveField(
            model_name="cancelamento",
            name="paga",
        ),
        migrations.AddField(
            model_name="cobranca",
            name="suspensa",
            field=models.BooleanField(
                default=False,
                help_text="Cobrança dentro de um período de trancamento (T16). A linha continua existindo, mas não é devida enquanto suspensa.",
                verbose_name="Suspensa?",
            ),
        ),
        migrations.AddField(
            model_name="cobranca",
            name="trancamento",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cobrancas_suspensas",
                to="financeiro.trancamento",
            ),
        ),
        migrations.AddField(
            model_name="regrafinanceira",
            name="limite_dias_trancamento_ano",
            field=models.PositiveIntegerField(
                default=90,
                help_text="Máximo de dias que uma matrícula pode ficar trancada em um ano.",
                validators=[django.core.validators.MaxValueValidator(365)],
                verbose_name="Limite de dias de trancamento por ano",
            ),
        ),
        migrations.AddField(
            model_name="trancamento",
            name="motivo",
            field=models.TextField(blank=True, verbose_name="Motivo"),
        ),
        migrations.AddField(
            model_name="trancamento",
            name="registrado_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="trancamento",
            name="registrado_por_nome",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="historicoregrafinanceira",
            name="campo",
            field=models.CharField(
                choices=[
                    ("dias_tolerancia", "Dias de tolerância"),
                    ("juros_diario", "Juros por dia de atraso (%)"),
                    ("multa_atraso", "Multa por atraso (%)"),
                    ("dias_bloqueio", "Dias de atraso que bloqueiam o acesso"),
                    (
                        "limite_dias_trancamento_ano",
                        "Limite de dias de trancamento por ano",
                    ),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="trancamento",
            name="data_fim",
            field=models.DateField(
                blank=True,
                help_text="Dia em que a matrícula volta a ficar ativa.",
                null=True,
                verbose_name="Data de retorno",
            ),
        ),
    ]
