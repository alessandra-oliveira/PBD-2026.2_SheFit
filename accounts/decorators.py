from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def perfil_requerido(*tipos_permitidos):
    """
    Exige que o usuário esteja autenticado e tenha
    um dos perfis permitidos.
    """
    def decorator(view_func):

        @wraps(view_func)
        @login_required(login_url='entrar')
        def wrapper(request, *args, **kwargs):

            perfil = getattr(request.user, 'perfil', None)

            if perfil is None or perfil.tipo not in tipos_permitidos:
                messages.error(
                    request,
                    'Você não tem permissão para acessar essa página.'
                )
                return redirect('painel')

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator