from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from accounts.decorators import perfil_requerido
from .servicos import processar_entrada_aluno

@login_required
@perfil_requerido('recepcao')
def tela_entrada_recepcao(request):
    """
    View da recepção para identificação e validação de acesso em tempo real (Tarefa T09).
    """
    resultado = None
    query = request.GET.get('q', '').strip()

    if query:
        resultado = processar_entrada_aluno(query)

    return render(request, 'recepcao/tela_entrada.html', {
        'resultado': resultado,
        'query': query
    })