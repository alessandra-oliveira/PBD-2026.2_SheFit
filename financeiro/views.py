from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from accounts.decorators import perfil_requerido
from .models import Plano, RegraFinanceira, HistoricoRegraFinanceira
from .forms import PlanoForm, RegraFinanceiraForm

@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def listar_planos(request):
    """
    Exibe todos os planos (ativos e inativos) para o gestor financeiro.
    """
    planos = Plano.objects.all().order_by('-ativo', 'nome')
    return render(request, 'financeiro/listar_planos.html', {'planos': planos})

@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def cadastrar_plano(request):
    """
    Cadastra um novo plano para a academia vender.
    """
    if request.method == 'POST':
        form = PlanoForm(request.POST)
        if form.is_valid():
            plano = form.save()
            messages.success(request, f'Plano "{plano.nome}" cadastrado com sucesso!')
            return redirect('listar_planos')
    else:
        form = PlanoForm()

    return render(request, 'financeiro/form_plano.html', {
        'form': form,
        'titulo': 'Novo Plano'
    })

@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def editar_plano(request, plano_id):
    """
    Edita as diretrizes de um plano.
    (Nota da regra T03: Não altera faturas passadas já geradas).
    """
    plano = get_object_or_404(Plano, pk=plano_id)

    if request.method == 'POST':
        form = PlanoForm(request.POST, instance=plano)
        if form.is_valid():
            form.save()
            messages.success(request, f'Plano "{plano.nome}" atualizado com sucesso!')
            return redirect('listar_planos')
    else:
        form = PlanoForm(instance=plano)

    return render(request, 'financeiro/form_plano.html', {
        'form': form,
        'plano': plano,
        'titulo': f'Editar {plano.nome}'
    })

@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def alternar_status_plano(request, plano_id):
    """
    Ativa/Desativa o plano rapidamente. Se desativado, some das novas matrículas.
    """
    plano = get_object_or_404(Plano, pk=plano_id)
    plano.ativo = not plano.ativo
    plano.save()

    status_str = "ativado" if plano.ativo else "desativado (oculto para novas matrículas)"
    messages.info(request, f'O plano "{plano.nome}" foi {status_str}.')
    return redirect('listar_planos')

@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def regras_financeiras(request):
    """
    T05 - Tela das regras financeiras globais (tolerância, juros, multa e bloqueio).
    Só o perfil financeiro acessa. Toda alteração fica registrada no histórico.
    """
    regras = RegraFinanceira.obter()

    if request.method == 'POST':
        form = RegraFinanceiraForm(request.POST, instance=regras)
        if form.is_valid():
            alterados = form.salvar(request.user)
            if alterados:
                messages.success(request, 'Regras financeiras atualizadas com sucesso!')
            else:
                messages.info(request, 'Nenhuma alteração foi feita nas regras.')
            return redirect('regras_financeiras')
    else:
        form = RegraFinanceiraForm(instance=regras)

    historico = HistoricoRegraFinanceira.objects.all()[:50]
    return render(request, 'financeiro/regras_financeiras.html', {
        'form': form,
        'regras': regras,
        'historico': historico,
    })
