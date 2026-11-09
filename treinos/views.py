from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from .forms import ExercicioTreinoFormSet, FichaTreinoForm
from .models import FichaTreino


@perfil_requerido('professor')
def listar_fichas(request):
    fichas = FichaTreino.objects.select_related('aluno', 'professor')
    return render(request, 'treinos/listar_fichas.html', {'fichas': fichas})


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
