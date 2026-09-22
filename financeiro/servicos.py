from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import RegraFinanceira, Matricula, Cobranca

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


def obter_total_meses_periodicidade(periodicidade):
    mapeamento = {
        'mensal': 1,
        'trimestral': 3,
        'semestral': 6,
        'anual': 12,
    }
    return mapeamento.get(str(periodicidade).lower(), 1)


@transaction.atomic
def realizar_matricula(aluno, plano, data_inicio, forma_pagamento):
    tem_anamnese = getattr(aluno, 'anamnese', None) is not None or getattr(aluno, 'tem_anamnese', True)
    tem_autorizacao = getattr(aluno, 'autorizacao', None) is not None or getattr(aluno, 'tem_autorizacao', True)
    
    if not tem_anamnese or not tem_autorizacao:
        raise ValidationError("Aluno sem anamnese ou autorização não pode ser matriculado.")

    matricula = Matricula.objects.create(
        aluno=aluno,
        plano=plano,
        data_inicio=data_inicio,
        forma_pagamento=forma_pagamento,
        status='ATIVA'
    )

    taxa_adesao = getattr(plano, 'taxa_adesao', Decimal('0.00'))
    if taxa_adesao and taxa_adesao > 0:
        Cobranca.objects.create(
            matricula=matricula,
            tipo='adesao',
            valor=taxa_adesao,
            vencimento=timezone.now().date(),
            competencia=None
        )

    total_meses = obter_total_meses_periodicidade(plano.periodicidade)
    data_atual = data_inicio

    for i in range(total_meses):
        competencia_str = data_atual.strftime('%Y-%m')
        
        dia_venc = getattr(plano, 'dia_vencimento', 10)
        try:
            vencimento = data_atual.replace(day=dia_venc)
        except ValueError:
            vencimento = (data_atual + relativedelta(day=31))

        try:
            Cobranca.objects.get_or_create(
                matricula=matricula,
                competencia=competencia_str,
                defaults={
                    'tipo': 'mensalidade',
                    'valor': plano.valor,
                    'vencimento': vencimento
                }
            )
        except IntegrityError:
            pass

        data_atual += relativedelta(months=1)

    return matricula