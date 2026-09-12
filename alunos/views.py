from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect

from accounts.models import Perfil
from accounts.decorators import perfil_requerido
from .forms import AlunoForm


@login_required
@perfil_requerido('recepcao')
def cadastrar_aluno(request):
    if request.method == 'POST':
        form = AlunoForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    password=form.cleaned_data['password'],
                )
                perfil = Perfil.objects.create(usuario=user, tipo=Perfil.ALUNO)
                aluno = form.save(commit=False)
                aluno.perfil = perfil
                aluno.save()

            messages.success(request, f'Aluno {aluno.nome} cadastrado com sucesso!')
            return redirect('cadastrar_aluno')
    else:
        form = AlunoForm()

    return render(request, 'alunos/cadastrar_aluno.html', {'form': form})