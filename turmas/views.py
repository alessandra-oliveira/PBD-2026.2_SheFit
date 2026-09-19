from django.shortcuts import render

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import perfil_requerido
from .models import Turma, Modalidade
from .forms import TurmaForm, ModalidadeForm


@perfil_requerido('recepcao', 'financeiro', 'professor')
def listar_turmas(request):
    if request.user.perfil.tipo == 'professor':
        # Professor só vê as turmas dele
        turmas = Turma.objects.filter(professor=request.user, ativo=True)
    else:
        # Recepção e financeiro veem todas
        turmas = Turma.objects.filter(ativo=True)

    return render(request, 'turmas/listar_turmas.html', {'turmas': turmas})


@perfil_requerido('recepcao', 'financeiro')
def criar_turma(request):
    if request.method == 'POST':
        form = TurmaForm(request.POST)
        if form.is_valid():
            turma = form.save(commit=False)
            turma.full_clean()  # roda o clean() do model também
            turma.save()
            messages.success(request, 'Turma cadastrada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = TurmaForm()

    return render(request, 'turmas/form_turma.html', {'form': form})


@perfil_requerido('recepcao', 'financeiro')
def editar_turma(request, turma_id):
    turma = get_object_or_404(Turma, id=turma_id)

    if request.method == 'POST':
        form = TurmaForm(request.POST, instance=turma)
        if form.is_valid():
            turma_editada = form.save(commit=False)
            turma_editada.full_clean()
            turma_editada.save()
            messages.success(request, 'Turma atualizada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = TurmaForm(instance=turma)

    return render(request, 'turmas/form_turma.html', {'form': form, 'turma': turma})


@perfil_requerido('recepcao', 'financeiro')
def desativar_turma(request, turma_id):
    # Substitui a exclusão: sempre desativa, nunca apaga de verdade.
    # Isso já cobre o critério "turma com aluno agendado não pode ser
    # excluída, só desativada" — porque simplesmente nunca excluímos,
    # sempre desativamos, independente de ter aluno ou não.
    turma = get_object_or_404(Turma, id=turma_id)
    turma.ativo = False
    turma.save()
    messages.success(request, 'Turma desativada.')
    return redirect('listar_turmas')


@perfil_requerido('recepcao', 'financeiro')
def criar_modalidade(request):
    if request.method == 'POST':
        form = ModalidadeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Modalidade cadastrada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = ModalidadeForm()

    return render(request, 'turmas/form_modalidade.html', {'form': form})
