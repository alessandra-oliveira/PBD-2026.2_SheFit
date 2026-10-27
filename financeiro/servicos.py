from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from django.db import transaction, IntegrityError
from django.db.models import Min, Q
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    RegraFinanceira, Matricula, Cobranca, SituacaoMatricula, Trancamento, Cancelamento,
)

CENTAVOS = Decimal('0.01')


def _centavos(valor):
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def esta_inadimplente(dias_atraso, regras=None):
    regras = regras or RegraFinanceira.obter()
    return dias_atraso > regras.dias_tolerancia


def acesso_bloqueado(dias_atraso, regras=None):
    regras = regras or RegraFinanceira.obter()
    return dias_atraso >= regras.dias_bloqueio


def calcular_situacao(matricula, hoje=None, regras=None):
    """Situação da matrícula em `hoje`. É a ÚNICA fonte da verdade (T08).

    Ordem de precedência (o primeiro que se aplica vence):
        cancelada > trancada > bloqueada > inadimplente > ativa

    O atraso é o da cobrança vencida e NÃO paga mais antiga, e reaproveita
    as regras já existentes (esta_inadimplente / acesso_bloqueado), então
    mudar a tolerância ou o limite de bloqueio muda a situação sozinho.
    Pagar a cobrança é o que "devolve" a matrícula a ativa: sem pendência,
    o cálculo cai no último return.
    """
    hoje = hoje or timezone.localdate()

    if Cancelamento.objects.filter(matricula=matricula).exists():
        return SituacaoMatricula.CANCELADA

    trancamento_em_curso = Trancamento.objects.filter(
        matricula=matricula, data_inicio__lte=hoje,
    ).filter(Q(data_fim__isnull=True) | Q(data_fim__gte=hoje)).exists()
    if trancamento_em_curso:
        return SituacaoMatricula.TRANCADA

    vencimento_mais_antigo = matricula.cobrancas.filter(
        paga=False, vencimento__lt=hoje,
    ).aggregate(mais_antigo=Min('vencimento'))['mais_antigo']
    if vencimento_mais_antigo is None:
        return SituacaoMatricula.ATIVA

    dias_atraso = (hoje - vencimento_mais_antigo).days
    regras = regras or RegraFinanceira.obter()
    if acesso_bloqueado(dias_atraso, regras):
        return SituacaoMatricula.BLOQUEADA
    if esta_inadimplente(dias_atraso, regras):
        return SituacaoMatricula.INADIMPLENTE
    return SituacaoMatricula.ATIVA


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


def _validar_aluno_para_matricula(aluno):
    """A anamnese é um OneToOne reverso (related_name='anamnese') e a
    autorização é o booleano `autorizacao_atividade_fisica` dentro dela.

    Sem anamnese, o Django levanta RelatedObjectDoesNotExist (subclasse de
    AttributeError); o getattr com default captura isso e devolve None.
    """
    anamnese = getattr(aluno, 'anamnese', None)
    if anamnese is None:
        raise ValidationError("Aluno sem anamnese não pode ser matriculado.")
    if not anamnese.autorizacao_atividade_fisica:
        raise ValidationError(
            "Aluno sem autorização para atividade física não pode ser matriculado."
        )


@transaction.atomic
def realizar_matricula(aluno, plano, data_inicio, forma_pagamento):
    _validar_aluno_para_matricula(aluno)

    matricula = Matricula.objects.create(
        aluno=aluno,
        plano=plano,
        data_inicio=data_inicio,
        forma_pagamento=forma_pagamento
    )

    taxa_adesao = getattr(plano, 'taxa_adesao', Decimal('0.00'))
    if taxa_adesao and taxa_adesao > 0:
        Cobranca.objects.create(
            matricula=matricula,
            tipo='adesao',
            valor=taxa_adesao,
            vencimento=timezone.localdate(),
            competencia=None
        )

    total_meses = obter_total_meses_periodicidade(plano.periodicidade)
    data_atual = data_inicio
    dia_venc = getattr(plano, 'dia_vencimento', 10)

    for _ in range(total_meses):
        competencia_str = data_atual.strftime('%Y-%m')

        try:
            vencimento = data_atual.replace(day=dia_venc)
        except ValueError:
            # Dia inexistente no mês (ex.: 31 em abril): usa o último dia do mês.
            vencimento = data_atual + relativedelta(day=31)

        try:
            # Savepoint próprio: se der IntegrityError, só este bloco é
            # desfeito e a transação externa continua utilizável.
            with transaction.atomic():
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


def avaliar_situacao_financeira_aluno(aluno):
    """
    Avalia a entrada do aluno a partir da SITUAÇÃO calculada da matrícula
    mais recente (T08), sem repetir regra nenhuma aqui (Tarefa T09).
    """
    matricula = Matricula.objects.filter(aluno=aluno).order_by('-data_inicio').first()

    if not matricula:
        return {
            'status': 'bloqueado',
            'motivo': 'Aluno sem matrícula registrada.'
        }

    hoje = timezone.localdate()
    regras = RegraFinanceira.obter()
    situacao = calcular_situacao(matricula, hoje=hoje, regras=regras)

    if situacao in (SituacaoMatricula.TRANCADA, SituacaoMatricula.CANCELADA):
        return {
            'status': 'bloqueado',
            'motivo': f'Matrícula com status: {situacao.label.upper()}.'
        }

    if situacao == SituacaoMatricula.ATIVA:
        return {
            'status': 'liberado',
            'motivo': 'Matrícula ativa e em dia.'
        }

    # Bloqueada ou inadimplente: há uma cobrança vencida em aberto
    cobranca_mais_antiga = matricula.cobrancas.filter(
        paga=False, vencimento__lt=hoje,
    ).order_by('vencimento').first()
    dias_atraso = (hoje - cobranca_mais_antiga.vencimento).days

    if situacao == SituacaoMatricula.BLOQUEADA:
        return {
            'status': 'bloqueado',
            'motivo': 'Inadimplente além do limite permitido.',
            'detalhes': {
                'valor_pendente': cobranca_mais_antiga.valor,
                'vencimento': cobranca_mais_antiga.vencimento,
                'dias_atraso': dias_atraso
            }
        }

    # Inadimplente, mas ainda abaixo do limite de bloqueio
    encargos = calcular_encargos(cobranca_mais_antiga.valor, dias_atraso, regras)
    valor_total_atualizado = cobranca_mais_antiga.valor + encargos['juros'] + encargos['multa']
    dias_restantes = regras.dias_bloqueio - dias_atraso
    return {
        'status': 'liberado_com_aviso',
        'motivo': f'Mensalidade em atraso. O acesso será bloqueado em {dias_restantes} dia(s).',
        'detalhes': {
            'valor_pendente': valor_total_atualizado,
            'vencimento': cobranca_mais_antiga.vencimento,
            'dias_atraso': dias_atraso,
            'dias_restantes_bloqueio': dias_restantes
        }
    }