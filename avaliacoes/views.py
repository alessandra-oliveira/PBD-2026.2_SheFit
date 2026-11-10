from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from .forms import AvaliacaoCorrecaoForm, AvaliacaoFisicaForm, testes_formset
from .models import AvaliacaoFisica
from .servicos import CAMPOS_COMPARAVEIS, comparar_avaliacoes

# Campos copiados da avaliação original para pré-preencher uma correção.
_CAMPOS_COPIADOS = [attr for attr, _, _ in CAMPOS_COMPARAVEIS if attr != 'imc'] + [
    'data_avaliacao', 'observacoes',
]


def _historico(aluno):
    """Série histórica COMPLETA do aluno (inclusive avaliações corrigidas),
    da mais recente para a mais antiga."""
    return list(
        aluno.avaliacoes_fisicas
        .select_related('professor', 'corrige')
        .prefetch_related('testes', 'correcoes')
    )


# ---------------------------------------------------------------------------
# Professor
# ---------------------------------------------------------------------------

@perfil_requerido('professor')
def listar_alunos(request):
    busca = request.GET.get('q', '').strip()
    alunos = Aluno.objects.annotate(
        total_avaliacoes=Count('avaliacoes_fisicas'),
        ultima_avaliacao=Max('avaliacoes_fisicas__data_avaliacao'),
    )
    if busca:
        alunos = alunos.filter(nome__icontains=busca)
    return render(request, 'avaliacoes/listar_alunos.html', {
        'alunos': alunos.order_by('nome'),
        'busca': busca,
    })


@perfil_requerido('professor')
def evolucao_aluno(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    return render(request, 'avaliacoes/evolucao.html', {
        'aluno': aluno,
        'avaliacoes': _historico(aluno),
        'eh_professor': True,
        'url_comparar': reverse('comparar_avaliacoes_aluno', args=[aluno.pk]),
        'url_voltar': reverse('avaliacoes_alunos'),
    })


@perfil_requerido('professor')
def registrar_avaliacao(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    FormSetTestes = testes_formset(extra=3)

    if request.method == 'POST':
        avaliacao = AvaliacaoFisica(aluno=aluno, professor=request.user)
        form = AvaliacaoFisicaForm(request.POST, instance=avaliacao)
        formset = FormSetTestes(request.POST, prefix='testes', instance=avaliacao)
        form_ok, formset_ok = form.is_valid(), formset.is_valid()
        if form_ok and formset_ok:
            with transaction.atomic():
                form.save()
                formset.instance = avaliacao
                formset.save()
            messages.success(request, 'Avaliação registrada com sucesso.')
            return redirect('avaliacoes_aluno', aluno_id=aluno.pk)
    else:
        form = AvaliacaoFisicaForm()
        formset = FormSetTestes(prefix='testes', instance=AvaliacaoFisica())

    return render(request, 'avaliacoes/form_avaliacao.html', {
        'aluno': aluno,
        'form': form,
        'formset': formset,
        'original': None,
    })


@perfil_requerido('professor')
def corrigir_avaliacao(request, avaliacao_id):
    """A avaliação é imutável: corrigir = registrar uma avaliação NOVA que
    aponta para a original e traz o motivo. A original não é tocada."""
    original = get_object_or_404(
        AvaliacaoFisica.objects.select_related('aluno').prefetch_related('testes', 'correcoes'),
        pk=avaliacao_id,
    )
    aluno = original.aluno

    if not original.vigente:
        messages.error(
            request,
            'Esta avaliação já foi corrigida. Corrija a versão mais recente.',
        )
        return redirect('avaliacoes_aluno', aluno_id=aluno.pk)

    if request.method == 'POST':
        FormSetTestes = testes_formset(extra=3)
        avaliacao = AvaliacaoFisica(aluno=aluno, professor=request.user, corrige=original)
        form = AvaliacaoCorrecaoForm(request.POST, instance=avaliacao)
        formset = FormSetTestes(request.POST, prefix='testes', instance=avaliacao)
        form_ok, formset_ok = form.is_valid(), formset.is_valid()
        if form_ok and formset_ok:
            try:
                with transaction.atomic():
                    form.save()
                    formset.instance = avaliacao
                    formset.save()
            except IntegrityError:
                # Duas pessoas corrigindo a mesma avaliação ao mesmo tempo.
                messages.error(
                    request,
                    'Esta avaliação acabou de ser corrigida por outra pessoa.',
                )
                return redirect('avaliacoes_aluno', aluno_id=aluno.pk)
            messages.success(request, 'Correção registrada. A avaliação original foi mantida no histórico.')
            return redirect('avaliacoes_aluno', aluno_id=aluno.pk)
    else:
        testes_originais = list(original.testes.all())
        FormSetTestes = testes_formset(extra=len(testes_originais) + 1)
        base = AvaliacaoFisica(
            aluno=aluno,
            corrige=original,
            **{campo: getattr(original, campo) for campo in _CAMPOS_COPIADOS},
        )
        form = AvaliacaoCorrecaoForm(instance=base)
        formset = FormSetTestes(
            prefix='testes',
            instance=AvaliacaoFisica(),
            initial=[
                {'nome': t.nome, 'resultado': t.resultado, 'unidade': t.unidade}
                for t in testes_originais
            ],
        )

    return render(request, 'avaliacoes/form_avaliacao.html', {
        'aluno': aluno,
        'form': form,
        'formset': formset,
        'original': original,
    })


@perfil_requerido('professor')
def comparar_avaliacoes_aluno(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    return _comparar(
        request, aluno,
        eh_professor=True,
        url_comparar=reverse('comparar_avaliacoes_aluno', args=[aluno.pk]),
        url_voltar=reverse('avaliacoes_aluno', args=[aluno.pk]),
    )


# ---------------------------------------------------------------------------
# Aluno (só enxerga as PRÓPRIAS avaliações)
# ---------------------------------------------------------------------------

@perfil_requerido('aluno')
def minha_evolucao(request):
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    return render(request, 'avaliacoes/evolucao.html', {
        'aluno': aluno,
        'avaliacoes': _historico(aluno),
        'eh_professor': False,
        'url_comparar': reverse('minha_comparacao'),
        'url_voltar': reverse('painel_aluno'),
    })


@perfil_requerido('aluno')
def minha_comparacao(request):
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    return _comparar(
        request, aluno,
        eh_professor=False,
        url_comparar=reverse('minha_comparacao'),
        url_voltar=reverse('minha_evolucao'),
    )


# ---------------------------------------------------------------------------
# Comparação (compartilhada por professor e aluno)
# ---------------------------------------------------------------------------

def _comparar(request, aluno, *, eh_professor, url_comparar, url_voltar):
    avaliacoes = _historico(aluno)
    por_id = {a.pk: a for a in avaliacoes}
    vigentes = [a for a in avaliacoes if a.vigente]

    parametro_a, parametro_b = request.GET.get('a'), request.GET.get('b')
    escolhida_a = escolhida_b = None

    if parametro_a is None and parametro_b is None:
        # Sem escolha: sugere as duas avaliações vigentes mais recentes.
        if len(vigentes) >= 2:
            escolhida_a, escolhida_b = vigentes[1], vigentes[0]
    else:
        # IDs de outro aluno (ou inexistentes) simplesmente não casam em `por_id`.
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

    return render(request, 'avaliacoes/comparar.html', {
        'aluno': aluno,
        'avaliacoes': avaliacoes,
        'total_vigentes': len(vigentes),
        'escolhida_a': escolhida_a,
        'escolhida_b': escolhida_b,
        'anterior': anterior,
        'posterior': posterior,
        'linhas': linhas,
        'eh_professor': eh_professor,
        'url_comparar': url_comparar,
        'url_voltar': url_voltar,
    })


def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None