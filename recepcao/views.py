from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from .models import Frequencia
from collections import Counter
from datetime import date

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from financeiro.models import Cancelamento, Cobranca, Matricula, Pagamento
from financeiro.servicos import (
    cancelar_matricula as efetuar_cancelamento,
    previsao_cancelamento,
    registrar_estorno as salvar_estorno,
    registrar_pagamento as salvar_pagamento,
    saldo_cobranca,
    simular_pagamento,
    total_estornado,
)

from .forms import CancelamentoForm, EstornoForm, LiberacaoExcepcionalForm, PagamentoForm
from .servicos import (
    LIMITE_RESULTADOS_BUSCA, avaliar_acesso, buscar_alunos,
    liberar_excepcionalmente, registrar_entrada,
)


def _aluno_ou_none(valor):
    try:
        pk = int(valor)
    except (TypeError, ValueError):
        return None
    return Aluno.objects.filter(pk=pk).first()


def _hora(frequencia):
    return timezone.localtime(frequencia.data_hora).strftime('%H:%M')


def _registrar(request):
    """POST: grava a entrada. É o ÚNICO caminho que cria frequência."""
    aluno = _aluno_ou_none(request.POST.get('aluno_id'))
    if aluno is None:
        messages.error(request, 'Aluna não identificada. Faça a busca novamente.')
        return redirect('tela_entrada_recepcao')

    resultado = registrar_entrada(aluno)

    if resultado['registrada']:
        messages.success(
            request, f"Entrada de {aluno.nome} registrada às {_hora(resultado['frequencia'])}.",
        )
        if resultado['status'] == 'liberado_com_aviso':
            messages.warning(request, f"Atenção: {resultado['mensagem']}")
    elif resultado['duplicada']:
        messages.info(
            request,
            f"A entrada de {aluno.nome} já foi registrada às "
            f"{_hora(resultado['frequencia'])}. Nada foi duplicado.",
        )
    else:
        messages.error(
            request, f"Acesso bloqueado para {aluno.nome}: {resultado['mensagem']}",
        )
    return redirect('tela_entrada_recepcao')

@login_required
@perfil_requerido('recepcao')
def liberar_excepcional(request):
    """Tarefa T10: libera a entrada de uma aluna bloqueada, com motivo.

    Só aceita POST. Grava uma Frequencia marcada como excepcional e não mexe
    em matrícula nem cobrança.
    """
    if request.method != 'POST':
        return redirect('tela_entrada_recepcao')

    aluno = _aluno_ou_none(request.POST.get('aluno_id'))
    if aluno is None:
        messages.error(request, 'Aluna não identificada. Faça a busca novamente.')
        return redirect('tela_entrada_recepcao')

    voltar = f"{reverse('tela_entrada_recepcao')}?aluno={aluno.pk}"

    form = LiberacaoExcepcionalForm(request.POST)
    if not form.is_valid():
        for erro in form.errors['motivo']:
            messages.error(request, erro)
        return redirect(voltar)

    resultado = liberar_excepcionalmente(
        aluno, form.cleaned_data['motivo'], request.user,
    )

    if resultado['erro']:
        messages.error(request, resultado['erro'])
        return redirect(voltar)
    if resultado['duplicada']:
        messages.info(
            request,
            f"A liberação de {aluno.nome} já foi registrada às "
            f"{_hora(resultado['frequencia'])}. Nada foi duplicado.",
        )
        return redirect('tela_entrada_recepcao')

    messages.success(
        request,
        f"Liberação excepcional de {aluno.nome} registrada às "
        f"{_hora(resultado['frequencia'])}.",
    )
    return redirect('tela_entrada_recepcao')

@login_required
@perfil_requerido('recepcao')
def tela_entrada_recepcao(request):
    """Controle de entrada (Tarefa T09).

    GET  -> só CONSULTA (identifica a aluna e mostra se o acesso está liberado).
            Buscar ou recarregar a página nunca grava nada.
    POST -> registra a entrada (botão "Registrar entrada").
    """
    if request.method == 'POST':
        return _registrar(request)

    query = request.GET.get('q', '').strip()
    resultado = None
    candidatos = None
    truncado = False
    nao_encontrado = False

    escolhida = _aluno_ou_none(request.GET.get('aluno'))
    if escolhida:
        resultado = avaliar_acesso(escolhida)
    elif query:
        alunos, truncado = buscar_alunos(query)
        if len(alunos) == 1:
            resultado = avaliar_acesso(alunos[0])
        elif alunos:
            candidatos = alunos
        else:
            nao_encontrado = True

    liberacao_hoje = None
    if resultado and not resultado['sucesso']:
        liberacao_hoje = (
            Frequencia.objects.filter(
                aluno=resultado['aluno'],
                excepcional=True,
                data_hora__date=timezone.localdate(),
            )
            .select_related('liberado_por')
            .first()
        )

    return render(request, 'recepcao/tela_entrada.html', {
        'resultado': resultado,
        'candidatos': candidatos,
        'truncado': truncado,
        'nao_encontrado': nao_encontrado,
        'limite': LIMITE_RESULTADOS_BUSCA,
        'query': query,
        'liberacao_hoje': liberacao_hoje,
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def listar_cobrancas_pagamento(request):
    cobrancas = (
        Cobranca.objects.filter(paga=False, cancelada=False)
        .select_related('matricula__aluno', 'matricula__plano')
        .prefetch_related('pagamentos__estornos')
        .order_by('vencimento', 'id')
    )
    hoje = timezone.localdate()
    itens = []
    for cobranca in cobrancas:
        saldo = saldo_cobranca(cobranca, hoje)
        if saldo > 0:
            itens.append({'cobranca': cobranca, 'saldo': saldo})
    return render(request, 'recepcao/selecionar_cobranca_pagamento.html', {
        'itens': itens,
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def registrar_pagamento(request, cobranca_id):
    cobranca = get_object_or_404(
        Cobranca.objects.select_related('matricula__aluno', 'matricula__plano')
        .prefetch_related('pagamentos__estornos'),
        pk=cobranca_id,
    )
    hoje = timezone.localdate()
    saldo_atual = saldo_cobranca(cobranca, hoje)
    quitada = saldo_atual <= 0

    preview = None
    form = PagamentoForm(request.POST or None) if not quitada else None
    if request.method == 'POST' and form is not None and form.is_valid():
        dados = form.cleaned_data
        try:
            simulacao = simular_pagamento(
                cobranca, dados['valor'], dados['data_pagamento'],
            )
            if request.POST.get('confirmar') == '1':
                salvar_pagamento(
                    cobranca,
                    dados['valor'],
                    dados['forma_pagamento'],
                    data_pagamento=dados['data_pagamento'],
                    observacoes=dados['observacoes'],
                    usuario=request.user,
                )
                messages.success(
                    request,
                    'Pagamento registrado. A situação da matrícula foi atualizada.',
                )
                return redirect('registrar_pagamento', cobranca_id=cobranca.pk)
            preview = simulacao
        except ValidationError as erro:
            for mensagem in erro.messages:
                form.add_error(None, mensagem)

    pagamentos = [
        {
            'pagamento': pagamento,
            'disponivel': pagamento.valor_pago - total_estornado(pagamento),
        }
        for pagamento in cobranca.pagamentos.all()
    ]
    return render(request, 'recepcao/registrar_pagamento.html', {
        'cobranca': cobranca,
        'saldo_atual': saldo_atual,
        'quitada': quitada,
        'form': form,
        'preview': preview,
        'pagamentos': pagamentos,
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def registrar_estorno(request, pagamento_id):
    pagamento = get_object_or_404(
        Pagamento.objects.select_related('cobranca__matricula__aluno')
        .prefetch_related('estornos'),
        pk=pagamento_id,
    )
    disponivel = pagamento.valor_pago - total_estornado(pagamento)
    if disponivel <= 0:
        messages.info(request, 'Este pagamento já foi totalmente estornado.')
        return redirect('registrar_pagamento', cobranca_id=pagamento.cobranca_id)

    form = EstornoForm(request.POST or None, initial={'valor': disponivel})
    if request.method == 'POST' and form.is_valid():
        try:
            salvar_estorno(
                pagamento,
                form.cleaned_data['valor'],
                form.cleaned_data['motivo'],
                request.user,
            )
            messages.success(
                request,
                'Estorno registrado. O pagamento original foi preservado.',
            )
            return redirect('registrar_pagamento', cobranca_id=pagamento.cobranca_id)
        except ValidationError as erro:
            for mensagem in erro.messages:
                form.add_error(None, mensagem)

    return render(request, 'recepcao/registrar_estorno.html', {
        'pagamento': pagamento,
        'disponivel': disponivel,
        'form': form,
    })

@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def buscar_matricula_cancelamento(request):
    """Tarefa T17: a recepção acha a aluna (CPF ou nome) e escolhe a matrícula a cancelar."""
    query = request.GET.get('q', '').strip()
    matriculas = []
    truncado = False
    if query:
        alunos, truncado = buscar_alunos(query)
        matriculas = list(
            Matricula.objects.filter(aluno__in=alunos, cancelamento__isnull=True)
            .select_related('aluno', 'plano')
            .order_by('aluno__nome', '-data_inicio')
        )
    return render(request, 'recepcao/buscar_cancelamento.html', {
        'query': query,
        'matriculas': matriculas,
        'truncado': truncado,
        'limite': LIMITE_RESULTADOS_BUSCA,
    })


def _avisos_do_cancelamento(request, matricula, resultado):
    """Resume na tela o que o cancelamento fez (valores já gravados)."""
    messages.success(
        request,
        f"Matrícula de {matricula.aluno.nome} cancelada em "
        f"{resultado['cancelamento'].data:%d/%m/%Y}.",
    )
    multa = resultado['cobranca_multa']
    if multa:
        messages.info(
            request,
            f"Multa de R$ {multa.valor} registrada como cobrança, com vencimento "
            f"em {multa.vencimento:%d/%m/%Y}.",
        )
    if resultado['canceladas']:
        messages.info(
            request,
            f"{len(resultado['canceladas'])} cobrança(s) futura(s) ainda não vencida(s) "
            f"cancelada(s).",
        )
    if resultado['canceladas_com_pagamento']:
        messages.warning(
            request,
            f"{len(resultado['canceladas_com_pagamento'])} cobrança(s) cancelada(s) já tinha(m) "
            f"pagamento. Confira com o financeiro se há valor a estornar.",
        )
    if resultado['total_dividas'] > 0:
        messages.warning(
            request,
            f"As cobranças vencidas e não pagas continuam como dívida: "
            f"R$ {resultado['total_dividas']} em aberto.",
        )


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def cancelar_matricula(request, matricula_id):
    """Tarefa T17: cancelamento da matrícula com a multa certa.

    GET  -> MOSTRA o valor da multa e o que vai acontecer; não grava nada.
    POST -> confirma. O valor que foi mostrado volta no POST e é conferido.
    Matrícula já cancelada mostra o resumo do que foi feito.
    """
    matricula = get_object_or_404(
        Matricula.objects.select_related('aluno', 'plano'), pk=matricula_id,
    )
    cancelamento = Cancelamento.objects.filter(matricula=matricula).first()
    hoje = timezone.localdate()

    if cancelamento is not None:
        if request.method == 'POST':
            messages.info(request, 'Esta matrícula já está cancelada.')
            return redirect('cancelar_matricula', matricula_id=matricula.pk)
        em_aberto = []
        for cobranca in (
            matricula.cobrancas.filter(paga=False, cancelada=False)
            .prefetch_related('pagamentos__estornos').order_by('vencimento', 'id')
        ):
            saldo = saldo_cobranca(cobranca, hoje)
            if saldo > 0:
                em_aberto.append({'cobranca': cobranca, 'saldo': saldo})
        return render(request, 'recepcao/cancelar_matricula.html', {
            'matricula': matricula,
            'cancelamento': cancelamento,
            'em_aberto': em_aberto,
            'canceladas': matricula.cobrancas.filter(cancelada=True).order_by('vencimento', 'id'),
        })

    form = None
    motivo_digitado = ''
    if request.method == 'POST':
        enviado = CancelamentoForm(request.POST)
        if enviado.is_valid():
            try:
                resultado = efetuar_cancelamento(
                    matricula,
                    enviado.cleaned_data['motivo'],
                    hoje=hoje,
                    multa_esperada=enviado.cleaned_data['multa_exibida'],
                )
            except ValidationError as erro:
                if erro.code == 'multa_divergente':
                    # Nada foi gravado: mostra de novo com o valor atual.
                    messages.warning(request, erro.messages[0])
                    motivo_digitado = enviado.cleaned_data['motivo']
                else:
                    for mensagem in erro.messages:
                        enviado.add_error(None, mensagem)
                    form = enviado
            else:
                _avisos_do_cancelamento(request, matricula, resultado)
                return redirect('cancelar_matricula', matricula_id=matricula.pk)
        else:
            form = enviado

    previsao = previsao_cancelamento(matricula, hoje)
    if form is None:
        form = CancelamentoForm(initial={'motivo': motivo_digitado})
    return render(request, 'recepcao/cancelar_matricula.html', {
        'matricula': matricula,
        'previsao': previsao,
        'form': form,
    })

def _data_ou_none(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


@login_required
@perfil_requerido('recepcao', 'financeiro')
def historico_liberacoes(request):
    """Tarefa T10: histórico de liberações excepcionais e total por atendente.

    Só consulta. Por padrão mostra o mês corrente.
    """
    hoje = timezone.localdate()
    inicio = _data_ou_none(request.GET.get('inicio')) or hoje.replace(day=1)
    fim = _data_ou_none(request.GET.get('fim')) or hoje

    liberacoes = list(
        Frequencia.objects.filter(
            excepcional=True,
            data_hora__date__gte=inicio,
            data_hora__date__lte=fim,
        )
        .select_related('aluno', 'liberado_por')
        .order_by('-data_hora')
    )

    por_atendente = Counter(
        str(l.liberado_por) if l.liberado_por else '—' for l in liberacoes
    ).most_common()

    return render(request, 'recepcao/historico_liberacoes.html', {
        'liberacoes': liberacoes,
        'por_atendente': por_atendente,
        'inicio': inicio,
        'fim': fim,
    })