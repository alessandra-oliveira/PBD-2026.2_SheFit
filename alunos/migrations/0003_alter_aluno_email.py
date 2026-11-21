

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alunos", "0002_alter_aluno_contato_emergencia_telefone_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aluno",
            name="email",
            field=models.EmailField(max_length=254, unique=True),
        ),
    ]
