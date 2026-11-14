"""Regras da tela "Os números da academia" (T21), sem HTTP e fáceis de testar."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from recepcao.models import Frequencia

# chave usada na URL -> (rótulo, quantidade de dias)
PERIODOS = {
    '7': ('Últimos 7 dias', 7),
    '30': ('Últimos 30 dias', 30),
    '90': ('Últimos 3 meses', 90),
    '365': ('Último ano', 365),
}
PERIODO_PADRAO = '30'


def normalizar_periodo(valor):
    """Devolve uma chave válida de PERIODOS (valor desconhecido cai no padrão)."""
    return valor if valor in PERIODOS else PERIODO_PADRAO


def frequencia_no_periodo(aluno, periodo, agora=None):
    """Conta os acessos da aluna no período.

    Só conta entradas efetivamente liberadas (`liberado=True`): uma tentativa
    barrada na recepção não é um acesso.
    """
    rotulo, dias = PERIODOS[normalizar_periodo(periodo)]
    agora = agora or timezone.now()
    desde = agora - timedelta(days=dias)
    total = Frequencia.objects.filter(
        aluno=aluno, liberado=True, data_hora__gte=desde, data_hora__lte=agora,
    ).count()
    media_semanal = (Decimal(total) / (Decimal(dias) / Decimal(7))).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP
    )
    return {
        'rotulo': rotulo,
        'dias': dias,
        'desde': desde,
        'total': total,
        'media_semanal': media_semanal,
    }