from collections import OrderedDict
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import Cobranca, Pagamento
from .servicos import saldo_cobranca


FAIXAS_ATRASO = (
    ('1 a 15 dias', 1, 15),
    ('16 a 30 dias', 16, 30),
    ('31 a 60 dias', 31, 60),
    ('Mais de 60 dias', 61, None),
)


def _faixa_atraso(dias):
    for nome, minimo, maximo in FAIXAS_ATRASO:
        if dias >= minimo and (maximo is None or dias <= maximo):
            return nome
    return None


def relatorio_inadimplencia(inicio, fim):
    """Monta as faixas e os itens vencidos em aberto no fim do período."""
    faixas = OrderedDict(
        (nome, {'nome': nome, 'total': Decimal('0.00'), 'quantidade': 0, 'itens': []})
        for nome, _, _ in FAIXAS_ATRASO
    )
    cobrancas = Cobranca.objects.filter(
        vencimento__gte=inicio,
        vencimento__lte=fim,
        vencimento__lt=fim,
        paga=False,
        cancelada=False,
        suspensa=False,
    ).select_related('matricula__aluno', 'matricula__plano').order_by('vencimento', 'id')


    for cobranca in cobrancas:
        dias_atraso = (fim - cobranca.vencimento).days
        faixa = _faixa_atraso(dias_atraso)
        if faixa is None:
            continue
        saldo = saldo_cobranca(cobranca, fim)
        item = {
            'aluna': cobranca.matricula.aluno.nome,
            'cobranca': cobranca,
            'valor': saldo,
            'dias_atraso': dias_atraso,
        }
        faixas[faixa]['total'] += saldo
        faixas[faixa]['quantidade'] += 1
        faixas[faixa]['itens'].append(item)

    return list(faixas.values())


def relatorio_receita(inicio, fim):
    """Compara cobranças previstas com pagamentos realizados no mesmo período."""
    previstas = Cobranca.objects.filter(
        vencimento__range=(inicio, fim),
        cancelada=False,
        suspensa=False,
    ).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')
    realizadas = Pagamento.objects.filter(
        data_pagamento__range=(inicio, fim),
    ).aggregate(total=Sum('valor_pago'))['total'] or Decimal('0.00')
    return {
        'prevista': previstas,
        'realizada': realizadas,
        'diferenca': previstas - realizadas,
    }
