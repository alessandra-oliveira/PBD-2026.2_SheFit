from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from .servicos import (
    LIMITE_RESULTADOS_BUSCA, avaliar_acesso, buscar_alunos, registrar_entrada,
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