from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from financeiro.models import Cobranca, Pagamento
from financeiro.servicos import (
    registrar_estorno as salvar_estorno,
    registrar_pagamento as salvar_pagamento,
    saldo_cobranca,
    simular_pagamento,
    total_estornado,
)
from .servicos import (
    LIMITE_RESULTADOS_BUSCA, avaliar_acesso, buscar_alunos, registrar_entrada,
)
from .forms import EstornoForm, PagamentoForm


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

    return render(request, 'recepcao/tela_entrada.html', {
        'resultado': resultado,
        'candidatos': candidatos,
        'truncado': truncado,
        'nao_encontrado': nao_encontrado,
        'limite': LIMITE_RESULTADOS_BUSCA,
        'query': query,
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def listar_cobrancas_pagamento(request):
    cobrancas = (
        Cobranca.objects.filter(paga=False)
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