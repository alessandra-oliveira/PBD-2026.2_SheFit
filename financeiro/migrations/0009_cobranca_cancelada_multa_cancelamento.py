

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0008_cancelamento_cancelada_cancelamento_paga'),
    ]

    operations = [
        migrations.AddField(
            model_name='cobranca',
            name='cancelada',
            field=models.BooleanField(default=False, help_text='Cobrança futura anulada pelo cancelamento da matrícula (T17). A linha continua existindo, mas não é mais devida.', verbose_name='Cancelada?'),
        ),
        migrations.AlterField(
            model_name='cobranca',
            name='tipo',
            field=models.CharField(choices=[('adesao', 'Taxa de Adesão'), ('mensalidade', 'Mensalidade'), ('multa_cancelamento', 'Multa de Cancelamento')], max_length=20, verbose_name='Tipo de Cobrança'),
        ),
    ]
