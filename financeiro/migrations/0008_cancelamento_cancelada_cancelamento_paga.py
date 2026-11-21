

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0007_sequencia_evento_por_cobranca'),
    ]

    operations = [
        migrations.AddField(
            model_name='cancelamento',
            name='cancelada',
            field=models.BooleanField(default=False, help_text='Cobrança futura anulada pelo cancelamento da matrícula (T17). A linha continua existindo, mas não é mais devida.', verbose_name='Cancelada?'),
        ),
        migrations.AddField(
            model_name='cancelamento',
            name='paga',
            field=models.BooleanField(default=False, verbose_name='Paga?'),
        ),
    ]
