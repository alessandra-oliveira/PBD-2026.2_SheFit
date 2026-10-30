from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from django.db import transaction, IntegrityError
from django.db.models import Min, Q
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    RegraFinanceira, Matricula, Cobranca, Pagamento, Estorno,
    SituacaoMatricula, Trancamento, Cancelamento,
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


def total_estornado(pagamento):
    return sum((item.valor for item in pagamento.estornos.all()), Decimal('0.00'))


def _alocacao_estorno(pagamento, valor_estorno, valor_disponivel):
    estornos = list(pagamento.estornos.all())
    juros_restantes = pagamento.juros - sum(
        (item.juros_estornados for item in estornos), Decimal('0.00'),
    )
    multa_restante = pagamento.multa - sum(
        (item.multa_estornada for item in estornos), Decimal('0.00'),
    )
    principal_restante = pagamento.principal_aplicado - sum(
        (item.principal_estornado for item in estornos), Decimal('0.00'),
    )
    if valor_estorno == valor_disponivel:
        return principal_restante, juros_restantes, multa_restante

    juros = min(
        valor_estorno,
        _centavos(juros_restantes * valor_estorno / valor_disponivel),
    )
    restante = valor_estorno - juros
    multa = min(
        restante,
        _centavos(multa_restante * valor_estorno / valor_disponivel),
    )
    principal = restante - multa
    if principal > principal_restante:
        excesso = principal - principal_restante
        principal = principal_restante
        multa = min(multa_restante, multa + excesso)
    return principal, juros, multa


def _estado_cobranca(cobranca, data_referencia=None):
    data_referencia = data_referencia or timezone.localdate()
    regras = RegraFinanceira.obter()
    principal = cobranca.valor
    juros_devido = Decimal('0.00')
    multa_devida = Decimal('0.00')
    multa_calculada = False
    inicio_juros = None
    ultima_data = cobranca.vencimento
    limite_tolerancia = cobranca.vencimento + timedelta(days=regras.dias_tolerancia)
    eventos = []

    pagamentos = cobranca.pagamentos.prefetch_related('estornos')
    for pagamento in pagamentos:
        eventos.append((
            pagamento.data_pagamento,
            pagamento.ordem_evento,
            pagamento,
            None,
        ))
        for estorno in pagamento.estornos.all():
            eventos.append((
                estorno.data_estorno,
                estorno.ordem_evento,
                pagamento,
                estorno,
            ))
    eventos.sort(key=lambda evento: evento[:2])

    def atualizar_encargos(data_evento):
        nonlocal juros_devido, multa_devida, multa_calculada, inicio_juros, ultima_data
        data_evento = min(data_evento, data_referencia)
        if data_evento <= ultima_data:
            return
        if data_evento > limite_tolerancia and principal > 0:
            if not multa_calculada:
                multa_devida += _centavos(principal * regras.multa_atraso / 100)
                multa_calculada = True
            data_inicio = inicio_juros or cobranca.vencimento
            dias = (data_evento - data_inicio).days
            if dias > 0:
                juros_devido += _centavos(principal * regras.juros_diario / 100 * dias)
                inicio_juros = data_evento
        ultima_data = data_evento

    for data_evento, _, pagamento, estorno in eventos:
        if data_evento > data_referencia:
            break
        atualizar_encargos(data_evento)
        if estorno is None:
            juros_devido = max(Decimal('0.00'), juros_devido - pagamento.juros)
            multa_devida = max(Decimal('0.00'), multa_devida - pagamento.multa)
            principal = max(Decimal('0.00'), principal - pagamento.principal_aplicado)
        else:
            principal += estorno.principal_estornado
            juros_devido += estorno.juros_estornados
            multa_devida += estorno.multa_estornada

    atualizar_encargos(data_referencia)
    principal = max(Decimal('0.00'), principal)
    juros_devido = max(Decimal('0.00'), juros_devido)
    multa_devida = max(Decimal('0.00'), multa_devida)
    return {
        'principal': principal,
        'juros': juros_devido,
        'multa': multa_devida,
        'total': principal + juros_devido + multa_devida,
    }


def saldo_cobranca(cobranca, data_referencia=None):
    return _estado_cobranca(cobranca, data_referencia)['total']


def simular_pagamento(cobranca, valor, data_pagamento=None):
    data_pagamento = data_pagamento or timezone.localdate()
    valor = _centavos(Decimal(str(valor)))
    if valor <= 0:
        raise ValidationError("O valor recebido deve ser maior que zero.")
    if data_pagamento > timezone.localdate():
        raise ValidationError("A data do pagamento não pode estar no futuro.")
    if cobranca.paga and not cobranca.pagamentos.exists():
        raise ValidationError("Esta cobrança já está quitada.")

    estado = _estado_cobranca(cobranca, data_pagamento)
    if estado['total'] <= 0:
        raise ValidationError("Esta cobrança já está quitada.")
    if valor > estado['total']:
        raise ValidationError(
            f"Valor recebido maior que o saldo atualizado da cobrança (R$ {estado['total']})."
        )

    juros = min(valor, estado['juros'])
    restante = valor - juros
    multa = min(restante, estado['multa'])
    principal_aplicado = min(restante - multa, estado['principal'])
    return {
        'juros': juros,
        'multa': multa,
        'principal_aplicado': principal_aplicado,
        'total': valor,
        'saldo_total': estado['total'],
        'saldo_restante': estado['total'] - valor,
    }


def atualizar_situacao(cobranca):
    paga = saldo_cobranca(cobranca) <= 0
    if cobranca.paga != paga:
        cobranca.paga = paga
        cobranca.save(update_fields=['paga'])


def _proxima_ordem_evento(cobranca):
    cobranca.ultima_sequencia_evento += 1
    cobranca.save(update_fields=['ultima_sequencia_evento'])
    return cobranca.ultima_sequencia_evento


@transaction.atomic
def registrar_pagamento(cobranca, valor, forma_pagamento, data_pagamento=None, observacoes='',
                        usuario=None):
    cobranca = Cobranca.objects.select_for_update().get(pk=cobranca.pk)
    data_pagamento = data_pagamento or timezone.localdate()
    formas_validas = dict(Matricula.FORMA_PAGAMENTO_CHOICES)
    if forma_pagamento not in formas_validas:
        raise ValidationError("Forma de pagamento inválida.")
    simulacao = simular_pagamento(cobranca, valor, data_pagamento)
    ordem_evento = _proxima_ordem_evento(cobranca)
    nome = (
        usuario.get_full_name() or usuario.get_username()
        if usuario is not None else 'Sistema'
    )
    pagamento = Pagamento.objects.create(
        cobranca=cobranca,
        ordem_evento=ordem_evento,
        valor_pago=simulacao['total'],
        data_pagamento=data_pagamento,
        forma_pagamento=forma_pagamento,
        juros=simulacao['juros'],
        multa=simulacao['multa'],
        principal_aplicado=simulacao['principal_aplicado'],
        observacoes=observacoes,
        registrado_por=usuario,
        registrado_por_nome=nome,
    )
    atualizar_situacao(cobranca)
    return pagamento


@transaction.atomic
def registrar_estorno(pagamento, valor, motivo, usuario):
    pagamento_id = pagamento.pk
    cobranca_id = Pagamento.objects.values_list(
        'cobranca_id', flat=True,
    ).get(pk=pagamento_id)
    cobranca = Cobranca.objects.select_for_update().get(pk=cobranca_id)
    pagamento = Pagamento.objects.select_for_update().get(pk=pagamento_id)
    if pagamento.cobranca_id != cobranca.pk:
        raise ValidationError("O pagamento foi associado a outra cobrança durante o estorno.")
    valor = _centavos(Decimal(str(valor)))
    motivo = (motivo or '').strip()
    disponivel = pagamento.valor_pago - total_estornado(pagamento)

    if valor <= 0:
        raise ValidationError("O valor do estorno deve ser maior que zero.")
    if not motivo:
        raise ValidationError("O motivo do estorno é obrigatório.")
    if valor > disponivel:
        raise ValidationError(f"Estorno maior que o disponível (máximo R$ {disponivel}).")

    principal, juros, multa = _alocacao_estorno(pagamento, valor, disponivel)
    ordem_evento = _proxima_ordem_evento(cobranca)
    estorno = Estorno.objects.create(
        pagamento=pagamento,
        ordem_evento=ordem_evento,
        valor=valor,
        principal_estornado=principal,
        juros_estornados=juros,
        multa_estornada=multa,
        motivo=motivo,
        estornado_por=usuario,
        estornado_por_nome=usuario.get_full_name() or usuario.get_username(),
    )
    atualizar_situacao(pagamento.cobranca)
    return estorno


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
    if not aluno.ativo:
        raise ValidationError("Aluno desativado não pode ser matriculado.")


def _vencimento_da_competencia(primeiro_dia_do_mes, dia_vencimento, data_inicio):
    """Vencimento da mensalidade de um mês.

    Dia inexistente no mês (ex.: 31 em abril) usa o último dia do mês.
    Nunca vence ANTES da data de início da matrícula: se o dia de vencimento
    do mês de entrada já passou, a 1ª mensalidade vence na própria data de
    início. Sem isso a aluna nasceria inadimplente no dia da matrícula.
    """
    try:
        vencimento = primeiro_dia_do_mes.replace(day=dia_vencimento)
    except ValueError:
        vencimento = primeiro_dia_do_mes + relativedelta(day=31)
    return max(vencimento, data_inicio)


@transaction.atomic
def gerar_cobrancas(matricula):
    """Gera as cobranças da matrícula (T06). É IDEMPOTENTE: pode rodar quantas
    vezes quiser para a mesma matrícula, que cada cobrança existe uma única vez.

        - adesão: no máximo uma por matrícula;
        - mensalidade: uma por (matrícula, competência).

    Devolve quantas cobranças foram criadas nesta execução (0 se já existiam).
    """
    plano = matricula.plano
    criadas = 0

    taxa_adesao = plano.taxa_adesao
    if taxa_adesao and taxa_adesao > 0:
        if not matricula.cobrancas.filter(tipo='adesao').exists():
            Cobranca.objects.create(
                matricula=matricula,
                tipo='adesao',
                valor=taxa_adesao,
                vencimento=timezone.localdate(),
                competencia=None,
            )
            criadas += 1

    primeiro_mes = matricula.data_inicio.replace(day=1)
    for i in range(obter_total_meses_periodicidade(plano.periodicidade)):
        mes = primeiro_mes + relativedelta(months=i)
        try:
            # Savepoint próprio: se a constraint única disparar numa corrida,
            # só este bloco é desfeito e a transação externa continua.
            with transaction.atomic():
                _, criada = Cobranca.objects.get_or_create(
                    matricula=matricula,
                    tipo='mensalidade',
                    competencia=mes.strftime('%Y-%m'),
                    defaults={
                        'valor': plano.valor,
                        'vencimento': _vencimento_da_competencia(
                            mes, plano.dia_vencimento, matricula.data_inicio,
                        ),
                    },
                )
        except IntegrityError:
            criada = False
        if criada:
            criadas += 1

    return criadas


@transaction.atomic
def realizar_matricula(aluno, plano, data_inicio, forma_pagamento):
    _validar_aluno_para_matricula(aluno)

    matricula = Matricula.objects.create(
        aluno=aluno,
        plano=plano,
        data_inicio=data_inicio,
        forma_pagamento=forma_pagamento,
    )
    gerar_cobrancas(matricula)
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
    valor_pendente = saldo_cobranca(cobranca_mais_antiga, hoje)

    if situacao == SituacaoMatricula.BLOQUEADA:
        return {
            'status': 'bloqueado',
            'motivo': 'Inadimplente além do limite permitido.',
            'detalhes': {
                'valor_pendente': valor_pendente,
                'vencimento': cobranca_mais_antiga.vencimento,
                'dias_atraso': dias_atraso
            }
        }

    # Inadimplente, mas ainda abaixo do limite de bloqueio
    dias_restantes = regras.dias_bloqueio - dias_atraso
    return {
        'status': 'liberado_com_aviso',
        'motivo': f'Mensalidade em atraso. O acesso será bloqueado em {dias_restantes} dia(s).',
        'detalhes': {
            'valor_pendente': valor_pendente,
            'vencimento': cobranca_mais_antiga.vencimento,
            'dias_atraso': dias_atraso,
            'dias_restantes_bloqueio': dias_restantes
        }
    }