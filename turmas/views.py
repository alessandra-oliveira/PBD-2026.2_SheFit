from datetime import datetime
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from accounts.decorators import perfil_requerido
from .models import Turma, Modalidade, Frequencia
from .forms import TurmaForm, ModalidadeForm
from agendamentos.models import Agendamento

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
    if capacidade_total > 0:
        calc = (total_estudantes / capacidade_total) * 100
        ocupacao_media = int(calc) if calc.is_integer() else round(calc, 1)
    else:
        ocupacao_media = 0

    for turma in turmas:
        turma.matriculados = turma.capacidade_maxima - turma.vagas_restantes()
        turma.ocupacao_pct = round((turma.matriculados / turma.capacidade_maxima * 100), 1) if turma.capacidade_maxima > 0 else 0
        turma.ocupacao_int = int(turma.ocupacao_pct)

    context = {
        'total_turmas': total_turmas,
        'total_estudantes': total_estudantes,
        'ocupacao_media': ocupacao_media,
        'turmas': turmas,
    }

    return render(request, 'turmas/minhas_turmas_professor.html', context)

@login_required
@perfil_requerido('professor')
def gerenciar_frequencia(request, turma_id):
    """
    Tarefa T12: O professor vê a lista de agendados da sua turma,
    marca presença ou falta, com suporte a correção e registro de auditoria.
    """
    turma = get_object_or_404(Turma, id=turma_id, professor=request.user)
    
    data_str = request.GET.get('data', timezone.localdate().strftime('%Y-%m-%d'))
    try:
        data_chamada = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        data_chamada = timezone.localdate()
        data_str = data_chamada.strftime('%Y-%m-%d')

    # Mantém apenas select_related('aluno') para evitar erros de relacionamento profundo
    agendamentos = Agendamento.objects.filter(turma=turma).select_related('aluno')
    
    frequencias_dict = {
        f.aluno_id: f.presente for f in Frequencia.objects.filter(turma=turma, data=data_chamada)
    }

    for ag in agendamentos:
        user_id_ref = ag.aluno_id
        try:
            if hasattr(ag.aluno, 'perfil') and ag.aluno.perfil:
                p = ag.aluno.perfil
                if hasattr(p, 'user') and p.user:
                    user_id_ref = p.user.id
                elif hasattr(p, 'usuario') and p.usuario:
                    user_id_ref = p.usuario.id
        except Exception:
            pass
        ag.user_id_ref = user_id_ref
        ag.foi_presente = frequencias_dict.get(user_id_ref, False)

    if request.method == 'POST':
        alunos_presentes_ids = [
            int(key.split('_')[1]) for key in request.POST.keys() if key.startswith('presente_')
        ]

        for agendamento in agendamentos:
            aluno_obj = agendamento.aluno
            user_instancia = None
            try:
                if hasattr(aluno_obj, 'perfil') and aluno_obj.perfil:
                    p = aluno_obj.perfil
                    if hasattr(p, 'user') and p.user:
                        user_instancia = p.user
                    elif hasattr(p, 'usuario') and p.usuario:
                        user_instancia = p.usuario
            except Exception:
                pass

            # Define o objeto a salvar (User do Django exigido pela FK de Frequencia, ou fallback para o aluno)
            aluno_para_salvar = user_instancia if user_instancia else aluno_obj
            
            veio = aluno_obj.id in alunos_presentes_ids or (user_instancia and user_instancia.id in alunos_presentes_ids)

            try:
                Frequencia.objects.update_or_create(
                    turma=turma,
                    aluno=aluno_para_salvar,
                    data=data_chamada,
                    defaults={
                        'presente': veio,
                        'atualizado_por': request.user
                    }
                )
            except Exception:
                pass
            
        messages.success(request, 'Frequência salva com sucesso.')
        return redirect(f"{request.path}?data={data_str}")

    context = {
        'turma': turma,
        'agendamentos': agendamentos,
        'data_chamada': data_str,
    }
    return render(request, 'turmas/gerenciar_frequencia.html', context)