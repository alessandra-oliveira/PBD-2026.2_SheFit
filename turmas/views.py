from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from accounts.decorators import perfil_requerido
from .models import Turma, Modalidade
from .forms import TurmaForm, ModalidadeForm

@login_required
@perfil_requerido('recepcao', 'financeiro', 'professor')
def listar_turmas(request):
    if request.user.perfil.tipo == 'professor':
        # Professor só vê as turmas dele
        turmas = Turma.objects.filter(professor=request.user, ativo=True)
    else:
        # Recepção e financeiro veem todas
        turmas = Turma.objects.filter(ativo=True)

    return render(request, 'turmas/listar_turmas.html', {'turmas': turmas})


@login_required
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


@login_required
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


@login_required(login_url='entrar')
@require_POST
@perfil_requerido('recepcao', 'financeiro')
def desativar_turma(request, turma_id):
    # Substitui a exclusão: sempre desativa, nunca apaga de verdade.
    turma = get_object_or_404(Turma, id=turma_id)
    turma.ativo = False
    turma.save()

    messages.success(request, 'Turma desativada.')

    return redirect('listar_turmas')

@login_required
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


@login_required
@perfil_requerido('professor')
def minhas_turmas_professor(request):
    """
    Área "Minhas Turmas" do Professor (Critério 4 do Kanban).
    Filtra exclusivamente as turmas ativas do professor logado e calcula as métricas de ocupação.
    """
    turmas_qs = Turma.objects.filter(professor=request.user, ativo=True).select_related('modalidade')
    turmas = list(turmas_qs)

    total_turmas = len(turmas)
    total_estudantes = sum(t.capacidade_maxima - t.vagas_restantes() for t in turmas)
    capacidade_total = sum(t.capacidade_maxima for t in turmas)
    ocupacao_media = round((total_estudantes / capacidade_total * 100), 1) if capacidade_total > 0 else 0

    for turma in turmas:
        turma.matriculados = turma.capacidade_maxima - turma.vagas_restantes()
        turma.ocupacao_pct = round((turma.matriculados / turma.capacidade_maxima * 100), 1) if turma.capacidade_maxima > 0 else 0
        turma.ocupacao_int = int(turma.ocupacao_pct)

    contexto = {
        'total_turmas': total_turmas,
        'total_estudantes': total_estudantes,
        'ocupacao_media': ocupacao_media,
        'turmas': turmas,
    }

    return render(request, 'turmas/minhas_turmas_professor.html', contexto)
