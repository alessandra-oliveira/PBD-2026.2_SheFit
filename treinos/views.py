from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from .forms import ExecucaoExercicioForm, ExercicioTreinoFormSet, FichaTreinoForm
from .models import Execucao, ExercicioTreino, FichaTreino
from .servicos import aderencia, evolucao_carga, ficha_ativa
from .servicos import registrar_execucao as registrar_execucao_servico


@perfil_requerido('professor')
def listar_fichas(request):
    fichas = FichaTreino.objects.select_related('aluno', 'professor').order_by('-criada_em')
    alunos = Aluno.objects.select_related('perfil').order_by('nome')
    return render(request, 'treinos/listar_fichas.html', {
        'fichas': fichas,
        'alunos': alunos,
    })


@perfil_requerido('professor')
def criar_ficha(request):
    if request.method == 'POST':
        form = FichaTreinoForm(request.POST)
        formset = ExercicioTreinoFormSet(request.POST, prefix='exercicios')
        if form.is_valid():
            ficha = form.save(commit=False)
            formset.instance = ficha
            if formset.is_valid():
                with transaction.atomic():
                    Aluno.objects.select_for_update().get(pk=ficha.aluno_id)
                    FichaTreino.objects.select_for_update().filter(
                        aluno_id=ficha.aluno_id,
                        ativa=True,
                    ).update(ativa=False, encerrada_em=timezone.now())
                    ficha.professor = request.user
                    ficha.save()
                    formset.instance = ficha
                    formset.save()
                messages.success(request, 'Ficha de treino criada com sucesso.')
                return redirect('detalhe_ficha', ficha_id=ficha.pk)
    else:
        form = FichaTreinoForm(initial={'aluno': request.GET.get('aluno')})
        formset = ExercicioTreinoFormSet(prefix='exercicios')

    aluno_selecionado = None
    anamnese = None
    if request.method == 'POST':
        aluno_id = (
            form.cleaned_data['aluno'].pk
            if form.is_valid()
            else request.POST.get('aluno')
        )
    else:
        aluno_id = request.GET.get('aluno')
    if aluno_id:
        aluno_selecionado = Aluno.objects.filter(pk=aluno_id).first()
        if aluno_selecionado:
            anamnese = getattr(aluno_selecionado, 'anamnese', None)

    return render(request, 'treinos/criar_ficha.html', {
        'form': form,
        'formset': formset,
        'aluno_selecionado': aluno_selecionado,
        'anamnese': anamnese,
    })


@perfil_requerido('professor')
def detalhe_ficha(request, ficha_id):
    ficha = get_object_or_404(
        FichaTreino.objects.select_related('aluno', 'professor').prefetch_related('exercicios'),
        pk=ficha_id,
    )
    return render(request, 'treinos/detalhe_ficha.html', {'ficha': ficha})


@perfil_requerido('aluno')
def ficha_ativa_aluno(request):
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    ficha = (
        FichaTreino.objects.filter(aluno=aluno, ativa=True)
        .select_related('aluno', 'professor')
        .prefetch_related('exercicios')
        .first()
    )
    return render(request, 'treinos/ficha_aluno.html', {'ficha': ficha})


# ---------------------------------------------------------------------------
# T21: registro de carga por exercício (view da main, mantida como está)
# ---------------------------------------------------------------------------

@perfil_requerido('aluno')
@require_POST
def registrar_execucao(request, exercicio_id):
    """A aluna registra a carga que usou num exercício da SUA ficha ativa."""
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    exercicio = get_object_or_404(
        ExercicioTreino, pk=exercicio_id, ficha__aluno=aluno, ficha__ativa=True,
    )
    form = ExecucaoExercicioForm(request.POST)
    if form.is_valid():
        execucao = form.save(commit=False)
        execucao.aluno = aluno
        execucao.exercicio = exercicio
        execucao.save()
        messages.success(request, f'Carga de {exercicio.nome} registrada.')
    else:
        erros = ' '.join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f'Não foi possível registrar {exercicio.nome}: {erros}')
    return redirect('ficha_ativa_aluno')


# ---------------------------------------------------------------------------
# T14: registro do treino (imutável), aderência e progressão de carga
# ---------------------------------------------------------------------------

def _data_ou_none(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def _carga_ou_none(texto):
    """'22,5' -> Decimal('22.50'). Vazio -> None. Inválido -> ValueError."""
    texto = (texto or '').strip().replace(',', '.')
    if not texto:
        return None
    try:
        valor = Decimal(texto).quantize(Decimal('0.01'))
    except InvalidOperation:
        raise ValueError('carga inválida')
    if not valor.is_finite() or valor < 0 or valor >= Decimal('1000000'):
        raise ValueError('carga inválida')
    return valor


@perfil_requerido('aluno')
def registrar_execucao_aluno(request):
    """Tarefa T14: o aluno marca o que fez na ficha ativa. Só aceita POST."""
    if request.method != 'POST':
        return redirect('ficha_ativa_aluno')

    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    ficha = ficha_ativa(aluno)
    if ficha is None:
        messages.error(request, 'Você não tem ficha de treino ativa.')
        return redirect('ficha_ativa_aluno')

    data = None
    data_txt = request.POST.get('data', '').strip()
    if data_txt:
        data = _data_ou_none(data_txt)
        if data is None:
            messages.error(request, 'Data inválida.')
            return redirect('ficha_ativa_aluno')

    itens = []
    for exercicio in ficha.exercicios.all():
        if not request.POST.get(f'feito_{exercicio.pk}'):
            continue
        try:
            carga = _carga_ou_none(request.POST.get(f'carga_{exercicio.pk}'))
        except ValueError:
            messages.error(request, f'Carga inválida em "{exercicio.nome}".')
            return redirect('ficha_ativa_aluno')
        itens.append({'exercicio_id': exercicio.pk, 'carga_efetiva': carga})

    try:
        registrar_execucao_servico(aluno, itens, request.POST.get('observacoes', ''), data)
    except ValidationError as erro:
        for mensagem in erro.messages:
            messages.error(request, mensagem)
        return redirect('ficha_ativa_aluno')

    messages.success(request, 'Treino registrado.')
    return redirect('ficha_ativa_aluno')


@perfil_requerido('aluno')
def evolucao_aluno(request):
    """Tarefa T14: o aluno vê a progressão de carga dele, por exercício."""
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)
    exercicios = []
    for nome, pontos in evolucao_carga(aluno).items():
        inicial, atual = pontos[0][1], pontos[-1][1]
        exercicios.append({
            'nome': nome,
            'pontos': pontos,
            'inicial': inicial,
            'atual': atual,
            'variacao': atual - inicial,
        })
    return render(request, 'treinos/evolucao_aluno.html', {'exercicios': exercicios})


@perfil_requerido('professor')
def execucoes_aluno(request, aluno_id):
    """Tarefa T14: o professor vê o histórico e a aderência de um aluno."""
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    hoje = timezone.localdate()
    inicio = _data_ou_none(request.GET.get('inicio')) or hoje - timedelta(days=30)
    fim = _data_ou_none(request.GET.get('fim')) or hoje
    execucoes = (
        Execucao.objects.filter(aluno=aluno, data__gte=inicio, data__lte=fim)
        .prefetch_related('itens')
    )
    return render(request, 'treinos/execucoes_aluno.html', {
        'aluno': aluno,
        'execucoes': execucoes,
        'aderencia': aderencia(aluno, inicio, fim),
        'inicio': inicio,
        'fim': fim,
    })