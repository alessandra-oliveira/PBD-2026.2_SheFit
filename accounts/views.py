from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as autenticar_sessao, logout as encerrar_sessao
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib import messages

def entrar(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        usuario = authenticate(username=username, password=password)

        if usuario is None: #login incorreto , com erro genérico
            return render(request, 'accounts/login.html', {
                'erro': 'Usuário ou senha inválidos'
            })

        if not hasattr(usuario, 'perfil'): #logou certo mas n tem perfil
            return render(request, 'accounts/login.html', {
                'erro': ' Usuário sem perfil atribuido.'
            })

        autenticar_sessao(request, usuario) #usuario loga

        return redirect('painel') #direciona o navegador pra url painel

    return render(request, 'accounts/login.html')

def sair(request):
    encerrar_sessao(request) #desloga o usuário
    return redirect('entrar') #volta pra tela de login

#redireciona cada um pro seu painel de acordo com o tipo
@login_required(login_url='entrar')
def painel(request):
    tipo = getattr(request.user.perfil, 'tipo', None)

    if tipo == 'aluno':
        return redirect('painel_aluno')
    elif tipo == 'professor':
        return redirect('painel_professor')
    elif tipo == 'recepcao':
        return redirect('painel_recepcao')
    elif tipo == 'financeiro':
        return redirect('painel_financeiro')
    else:
        raise PermissionDenied #bloqueia se n tiver tipo valido

#telas de cada perfil, só entra quem tem o tipo certo
@login_required(login_url='entrar')
@login_required(login_url='entrar')
@login_required(login_url='entrar')
def painel_aluno(request):
    if request.user.perfil.tipo != 'aluno':
        raise PermissionDenied

    aluno = getattr(request.user.perfil, 'aluno', None)

    return render(request, 'accounts/painel_aluno.html', {'aluno': aluno})

@login_required(login_url='entrar')
def painel_professor(request):
    if request.user.perfil.tipo != 'professor':
        raise PermissionDenied
    return render(request, 'accounts/painel_professor.html')

@login_required(login_url='entrar')
def painel_recepcao(request):
    if request.user.perfil.tipo != 'recepcao':
        raise PermissionDenied
    return render(request, 'accounts/painel_recepcao.html')

@login_required(login_url='entrar')
def painel_financeiro(request):
    if request.user.perfil.tipo != 'financeiro':
        raise PermissionDenied
    return render(request, 'accounts/painel_financeiro.html')