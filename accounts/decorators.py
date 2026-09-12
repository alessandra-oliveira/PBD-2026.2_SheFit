from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect


def perfil_requerido(*tipos_permitidos):
    """
    Decorator que exige que o usuário logado tenha um Perfil
    com um dos tipos permitidos (ex: 'recepcao', 'professor').

    Uso:
        @perfil_requerido('recepcao')
        def minha_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            perfil = getattr(request.user, 'perfil', None)

            if perfil is None or perfil.tipo not in tipos_permitidos:
                messages.error(request, 'Você não tem permissão para acessar essa página.')
                return redirect('painel')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator