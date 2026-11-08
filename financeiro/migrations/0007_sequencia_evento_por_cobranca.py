from collections import defaultdict

from django.db import migrations, models


def preencher_sequencias_historicas(apps, schema_editor):
    alias = schema_editor.connection.alias
    Cobranca = apps.get_model("financeiro", "Cobranca")
    Pagamento = apps.get_model("financeiro", "Pagamento")
    Estorno = apps.get_model("financeiro", "Estorno")
    eventos_por_cobranca = defaultdict(list)

    pagamentos = Pagamento.objects.using(alias).values_list(
        "id", "cobranca_id", "data_pagamento", "criado_em",
    )
    for evento_id, cobranca_id, data_evento, criado_em in pagamentos.iterator():
        eventos_por_cobranca[cobranca_id].append(
            (data_evento, criado_em, "Pagamento", evento_id),
        )

    estornos = Estorno.objects.using(alias).values_list(
        "id", "pagamento__cobranca_id", "data_estorno", "criado_em",
    )
    for evento_id, cobranca_id, data_evento, criado_em in estornos.iterator():
        eventos_por_cobranca[cobranca_id].append(
            (data_evento, criado_em, "Estorno", evento_id),
        )

    ambiguidades = []
    for cobranca_id, eventos in eventos_por_cobranca.items():
        ordenados = sorted(eventos, key=lambda evento: (evento[0], evento[1]))
        for anterior, atual in zip(ordenados, ordenados[1:]):
            if anterior[:2] == atual[:2]:
                ambiguidades.append(
                    f"cobranca={cobranca_id}, data={atual[0]}, "
                    f"criado_em={atual[1]}, eventos="
                    f"{anterior[2]}#{anterior[3]} e {atual[2]}#{atual[3]}"
                )

    if ambiguidades:
        detalhes = "\n".join(ambiguidades)
        raise RuntimeError(
            "Não foi possível migrar a sequência dos eventos financeiros: "
            "há eventos da mesma cobrança, data contábil e timestamp de criação "
            "idênticos. Resolva a ordem com evidência externa antes de migrar:\n"
            f"{detalhes}"
        )

    for cobranca_id, eventos in eventos_por_cobranca.items():
        ordenados = sorted(eventos, key=lambda evento: (evento[0], evento[1]))
        for ordem, (_, _, tipo, evento_id) in enumerate(ordenados, start=1):
            modelo = Pagamento if tipo == "Pagamento" else Estorno
            modelo.objects.using(alias).filter(pk=evento_id).update(
                ordem_evento=ordem,
            )
        Cobranca.objects.using(alias).filter(pk=cobranca_id).update(
            ultima_sequencia_evento=len(ordenados),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("financeiro", "0006_pagamento_estorno"),
    ]

    operations = [
        migrations.AddField(
            model_name="cobranca",
            name="ultima_sequencia_evento",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="pagamento",
            name="ordem_evento",
            field=models.PositiveBigIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="estorno",
            name="ordem_evento",
            field=models.PositiveBigIntegerField(null=True),
        ),
        migrations.RunPython(
            preencher_sequencias_historicas,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="pagamento",
            name="ordem_evento",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AlterField(
            model_name="estorno",
            name="ordem_evento",
            field=models.PositiveBigIntegerField(),
        ),
    ]
