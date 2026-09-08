from django.shortcuts import render, redirect
from django.contrib.auth import  authenticate , login  as autenticar_sessao , logout as encerrar_sessao

def entrar(request):
    if  request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        usuario = authenticate(username = username , password = password)

        if usuario is None: #login incorreto , com erro genérico
            return render(request, 'accounts/login.html' , {
                'erro': 'Usuário ou senha inválidos'
            } )

        if not hasattr(usuario , 'perfil'): #logou certo mas n tem perfil
            return render(request, 'accounts/login.html' , {
                'erro': ' Usuário sem perfil atribuido.'
            })

        autenticar_sessao(request, usuario) #usuario loga

        return redirect('painel') #direciona o navegador pra url painel

    return render(request, 'accounts/login.html')

def sair(request):
    encerrar_sessao(request)#desloga o usuário
    return redirect('entrar')#volta pra tela de login