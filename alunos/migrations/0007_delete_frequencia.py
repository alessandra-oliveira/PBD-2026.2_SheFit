

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('alunos', '0006_frequencia'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Frequencia',
        ),
    ]
