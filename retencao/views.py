from django.contrib import messages
from django.shortcuts import get_object_or_404, render

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from avaliacoes.servicos import chave_cronologica, comparar_avaliacoes

from .servicos import PERIODOS, frequencia_no_periodo, normalizar_periodo


def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@perfil_requerido('aluno')
def numeros_da_academia(request):
    """Tela de retenção: a aluna vê o quanto veio e o quanto mudou.

    Só mostra os dados da PRÓPRIA aluna logada.
    """
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)

    # 1. Frequência por período
    periodo = normalizar_periodo(request.GET.get('periodo'))
    frequencia = frequencia_no_periodo(aluno, periodo)

    # 3. Série histórica completa (inclui as corrigidas, marcadas), da mais antiga à mais nova
    avaliacoes = sorted(
        aluno.avaliacoes_fisicas.select_related('corrige').prefetch_related('testes', 'correcoes'),
        key=chave_cronologica,
    )
    por_id = {a.pk: a for a in avaliacoes}
    vigentes = [a for a in avaliacoes if a.vigente]

    # 4. Comparação entre duas avaliações escolhidas
    parametro_a, parametro_b = request.GET.get('a'), request.GET.get('b')
    escolhida_a = escolhida_b = None
    if parametro_a is None and parametro_b is None:
        if len(vigentes) >= 2:
            escolhida_a, escolhida_b = vigentes[-2], vigentes[-1]
    else:
        escolhida_a = por_id.get(_inteiro(parametro_a))
        escolhida_b = por_id.get(_inteiro(parametro_b))
        if escolhida_a is None or escolhida_b is None:
            messages.error(request, 'Escolha duas avaliações da lista.')
            escolhida_a = escolhida_b = None
        elif escolhida_a.pk == escolhida_b.pk:
            messages.error(request, 'Escolha duas avaliações diferentes para comparar.')
            escolhida_a = escolhida_b = None

    anterior = posterior = None
    linhas = []
    if escolhida_a and escolhida_b:
        anterior, posterior, linhas = comparar_avaliacoes(escolhida_a, escolhida_b)

    return render(request, 'retencao/numeros_da_academia.html', {
        'aluno': aluno,
        'periodos': [(chave, rotulo) for chave, (rotulo, _) in PERIODOS.items()],
        'periodo': periodo,
        'frequencia': frequencia,
        'avaliacoes': avaliacoes,
        'escolhida_a': escolhida_a,
        'escolhida_b': escolhida_b,
        'anterior': anterior,
        'posterior': posterior,
        'linhas': linhas,
    })