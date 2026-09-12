from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Perfil
from accounts.decorators import perfil_requerido
from .models import Aluno, Anamnese
from .forms import AlunoForm, AnamneseForm


@login_required
@perfil_requerido('recepcao')
def cadastrar_aluno(request):
    if request.method == 'POST':
        form = AlunoForm(request.POST, request.FILES)
        if form.is_valid():
            aluno = form.save(commit=False)
            aluno.ativo = False  # Bloqueado até a conclusão da anamnese
            aluno.save()
            
            messages.info(
                request, 
                'Cadastro inicial realizado! O aluno só será matriculado e ativado após o preenchimento da anamnese médica e aceite do termo de aptidão física.'
            )
            return redirect('preencher_anamnese', aluno_id=aluno.id)
    else:
        form = AlunoForm()

    return render(request, 'alunos/cadastrar_aluno.html', {'form': form})

@login_required
@perfil_requerido('recepcao')
def preencher_anamnese(request, aluno_id):
    """
    Formulário de saúde: preenchido pela recepção.
    Se a autorização for confirmada, o aluno é liberado/matriculado.
    """
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    anamnese_instance = getattr(aluno, 'anamnese', None)

    if request.method == 'POST':
        form = AnamneseForm(request.POST, instance=anamnese_instance)
        if form.is_valid():
            anamnese = form.save(commit=False)
            anamnese.aluno = aluno
            anamnese.save()

            # Regra dura de matrícula/ativação
            if anamnese.autorizacao_atividade_fisica:
                aluno.ativo = True
                aluno.save()
                messages.success(request, f'Anamnese e autorização confirmadas! Matrícula de {aluno.nome} liberada com sucesso.')
                # Redireciona para a tela de consulta da anamnese recém-criada
                return redirect('consultar_anamnese', aluno_id=aluno.id)
            else:
                aluno.ativo = False
                aluno.save()
                messages.error(request, 'Não é possível matricular o aluno: o termo de autorização para atividade física não foi marcado.')
    else:
        form = AnamneseForm(instance=anamnese_instance)

    return render(request, 'alunos/preencher_anamnese.html', {
        'form': form,
        'aluno': aluno
    })


@login_required
@perfil_requerido('professor')
def consultar_anamnese(request, aluno_id):
    """
    Visão do professor: consulta rápida das restrições e lesões antes do treino.
    """
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    anamnese = getattr(aluno, 'anamnese', None)

    if not anamnese:
        messages.warning(request, f'O aluno {aluno.nome} ainda não possui ficha de anamnese cadastrada.')

    return render(request, 'alunos/consultar_anamnese.html', {
        'aluno': aluno,
        'anamnese': anamnese
    })