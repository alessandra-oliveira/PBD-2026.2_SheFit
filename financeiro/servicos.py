from decimal import Decimal, ROUND_HALF_UP

from .models import RegraFinanceira

CENTAVOS = Decimal('0.01')


def _centavos(valor):
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def esta_inadimplente(dias_atraso, regras=None):
    regras = regras or RegraFinanceira.obter()
    return dias_atraso > regras.dias_tolerancia


def acesso_bloqueado(dias_atraso, regras=None):
    regras = regras or RegraFinanceira.obter()
    return dias_atraso >= regras.dias_bloqueio


def calcular_encargos(valor, dias_atraso, regras=None):
    regras = regras or RegraFinanceira.obter()
    valor = Decimal(str(valor))
    if dias_atraso <= regras.dias_tolerancia:
        return {'juros': Decimal('0.00'), 'multa': Decimal('0.00')}
    juros = _centavos(valor * regras.juros_diario / 100 * dias_atraso)
    multa = _centavos(valor * regras.multa_atraso / 100)
    return {'juros': juros, 'multa': multa}