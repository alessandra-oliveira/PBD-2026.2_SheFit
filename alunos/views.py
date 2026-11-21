from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import date

from accounts.decorators import perfil_requerido
from financeiro.servicos import realizar_matricula
from .models import Aluno, Anamnese
from .forms import AlunoForm, AnamneseForm, MatriculaForm
from financeiro.models import Matricula, Cobranca, Pagamento, RegraFinanceira


@login_required
@perfil_requerido('recepcao')
def cadastrar_aluno(request):
    if request.method == 'POST':
        form = AlunoForm(request.POST, request.FILES)
        if form.is_valid():
            # Cria Usuário + Perfil + Aluno (inativo até uma anamnese autorizada)
            aluno = form.save()

            messages.info(
                request,
                'Cadastro inicial realizado! O aluno só será matriculado e ativado após o preenchimento da anamnese médica e aceitar o termo de entrega física.'
            )
            return redirect('preencher_anamnese', aluno_id=aluno.id)
    else:
        form = AlunoForm()

    return render(request, 'alunos/cadastrar_aluno.html', {'form': form})


@login_required
@perfil_requerido('recepcao')
def preencher_anamnese(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    anamnese_instance = getattr(aluno, 'anamnese', None)
    if request.method == 'POST':
        form = AnamneseForm(request.POST, instance=anamnese_instance)
        if form.is_valid():
            anamnese = form.save(commit=False)
            anamnese.aluno = aluno
            anamnese.save()
            if anamnese.autorizacao_atividade_fisica:
                aluno.ativo = True
                aluno.save()
                messages.success(request, f'Anamnese e autorização confirmadas! {aluno.nome} já pode ser matriculada.')
                # Volta ao painel da recepção. (A tela de consulta é só do
                # professor: redirecionar para lá daria "sem permissão".)
                return redirect('painel_recepcao')
            else:
                aluno.ativo = False
                aluno.save()
                messages.error(request, 'Termo não marcado.')
    else:
        form = AnamneseForm(instance=anamnese_instance)
    return render(request, 'alunos/preencher_anamnese.html', {'form': form, 'aluno': aluno})


@login_required
@perfil_requerido('professor')
def consultar_anamnese(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    anamnese = getattr(aluno, 'anamnese', None)
    if not anamnese:
        messages.warning(request, f'O aluno {aluno.nome} não possui ficha.')
    return render(request, 'alunos/consultar_anamnese.html', {'aluno': aluno, 'anamnese': anamnese})


@login_required
@perfil_requerido('recepcao')
def editar_aluno(request, aluno_id):
    aluno = get_object_or_404(Aluno, pk=aluno_id)
    if request.method == 'POST':
        form = AlunoForm(request.POST, request.FILES, instance=aluno)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados atualizados com sucesso!')
            return redirect('painel_recepcao')
    else:
        form = AlunoForm(instance=aluno)

    return render(request, 'alunos/editar_aluno.html', {'form': form, 'aluno': aluno})


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def criar_matricula(request):
    """
    Realiza a matrícula do aluno, acionando o serviço financeiro para gerar as cobranças automáticas.
    """
    if request.method == 'POST':
        form = MatriculaForm(request.POST)
        if form.is_valid():
            try:
                realizar_matricula(
                    aluno=form.cleaned_data['aluno'],
                    plano=form.cleaned_data['plano'],
                    data_inicio=form.cleaned_data['data_inicio'],
                    forma_pagamento=form.cleaned_data['forma_pagamento']
                )
                messages.success(request, "Matrícula realizada com sucesso e cobranças geradas automaticamente!")
                return redirect('criar_matricula')
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = MatriculaForm()

    return render(request, 'alunos/nova_matricula.html', {'form': form})

@login_required
@perfil_requerido('aluno')
def minha_situacao_financeira(request):
    """
    Tarefa T19: Área de consulta financeira e de matrícula do aluno.
    Exibe status, cobranças em aberto, dias para bloqueio, vigência e histórico.
    Somente leitura (nenhuma edição permitida).
    """
    # Isola estritamente o aluno logado para garantir segurança de dados
    aluno = getattr(request.user, 'aluno', None)
    if not aluno and hasattr(request.user, 'perfil'):
        try:
            aluno = request.user.perfil.aluno
        except Exception:
            aluno = None
    if not aluno:
        aluno = Aluno.objects.filter(perfil__usuario=request.user).first()

    matricula = None
    cobrancas_aberto = []
    total_aberto = 0
    historico_pagamentos = []
    dias_para_bloqueio = None
    regra = RegraFinanceira.obter()
    hoje = date.today()

    if aluno:
        # Pega a matrícula mais recente do aluno
        matricula = Matricula.objects.filter(aluno=aluno).select_related('plano').order_by('-id').first()

        if matricula:
            # Busca cobranças não pagas
            cobrancas_aberto = Cobranca.objects.filter(matricula=matricula, paga=False).order_by('vencimento')
            total_aberto = sum(c.valor for c in cobrancas_aberto)

            # Calcula os dias para bloqueio se houver atraso
            cobrancas_vencidas = [c for c in cobrancas_aberto if c.vencimento < hoje]
            if cobrancas_vencidas:
                cobranca_mais_antiga = min(cobrancas_vencidas, key=lambda x: x.vencimento)
                dias_atraso = (hoje - cobranca_mais_antiga.vencimento).days
                dias_para_bloqueio = regra.dias_bloqueio - dias_atraso

            # Histórico de pagamentos do aluno
            historico_pagamentos = Pagamento.objects.filter(
                cobranca__matricula=matricula
            ).select_related('cobranca').order_by('-data_pagamento')

    context = {
        'aluno': aluno,
        'matricula': matricula,
        'cobrancas_aberto': cobrancas_aberto,
        'total_aberto': total_aberto,
        'historico_pagamentos': historico_pagamentos,
        'dias_para_bloqueio': dias_para_bloqueio,
        'regra_financeira': regra,
        'today': hoje,
    }

    return render(request, 'alunos/minha_situacao.html', context)