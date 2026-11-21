from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from accounts.decorators import perfil_requerido
from .models import (
    Plano, RegraFinanceira, HistoricoRegraFinanceira, Matricula, Cobranca,
    Pagamento, Trancamento,
)
from .forms import PlanoForm, RegraFinanceiraForm, RelatorioPeriodoForm
from django.core.exceptions import ValidationError
from django.contrib import messages
from financeiro.servicos import trancar_matricula, dias_trancados
from .forms import TrancamentoForm
from .relatorios import relatorio_inadimplencia, relatorio_receita


def obter_metricas_dashboard():
    """
    Consolida todos os dados reais do banco para o Dashboard Financeiro.
    """
    hoje = timezone.localdate()
    ano_atual = hoje.year
    mes_atual = hoje.month


    total_recebido = Pagamento.objects.filter(
        data_pagamento__year=ano_atual,
        data_pagamento__month=mes_atual
    ).aggregate(total=Sum('valor_pago'))['total'] or Decimal('0.00')


    a_receber = Cobranca.objects.filter(
        vencimento__year=ano_atual,
        vencimento__month=mes_atual,
        paga=False
    ).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')

    qtd_a_receber = Cobranca.objects.filter(
        vencimento__year=ano_atual,
        vencimento__month=mes_atual,
        paga=False
    ).count()


    receita_mes = total_recebido + a_receber
    if receita_mes == Decimal('0.00'):
        cobrancas_total_mes = Cobranca.objects.filter(
            vencimento__year=ano_atual,
            vencimento__month=mes_atual
        ).aggregate(total=Sum('valor'))['total'] or Decimal('0.00')
        receita_mes = cobrancas_total_mes


    mes_ant = mes_atual - 1 if mes_atual > 1 else 12
    ano_ant = ano_atual if mes_atual > 1 else ano_atual - 1
    receita_mes_ant = Pagamento.objects.filter(
        data_pagamento__year=ano_ant,
        data_pagamento__month=mes_ant
    ).aggregate(total=Sum('valor_pago'))['total'] or Decimal('0.00')

    if receita_mes_ant > 0:
        crescimento_pct = ((receita_mes - receita_mes_ant) / receita_mes_ant) * 100
    else:
        crescimento_pct = Decimal('0.0')

    pct_recebido_previsto = (total_recebido / receita_mes * 100) if receita_mes > 0 else Decimal('0.0')


    matriculas = Matricula.objects.select_related('plano', 'aluno').all()
    assinaturas_ativas = sum(1 for m in matriculas if m.situacao == 'ativa')
    novos_planos_mes = Matricula.objects.filter(
        criado_em__year=ano_atual,
        criado_em__month=mes_atual
    ).count()


    nomes_meses_abrev = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    evolucao_meses = []
    for i in range(5, -1, -1):
        m_num = (mes_atual - i - 1) % 12 + 1
        y_num = ano_atual if (mes_atual - i) > 0 else ano_atual - 1

        val_mes = Pagamento.objects.filter(
            data_pagamento__year=y_num,
            data_pagamento__month=m_num
        ).aggregate(total=Sum('valor_pago'))['total'] or Decimal('0.00')

        evolucao_meses.append({
            'mes': nomes_meses_abrev[m_num - 1],
            'ano': y_num,
            'valor': val_mes,
            'valor_formatado': f"R$ {val_mes:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        })

    valores_meses = [item['valor'] for item in evolucao_meses]
    max_val = max(valores_meses) if valores_meses and max(valores_meses) > 0 else Decimal('1.00')
    for item in evolucao_meses:
        if item['valor'] > 0:
            item['altura_pct'] = min(100, max(15, int((item['valor'] / max_val) * 100)))
        else:
            item['altura_pct'] = 8


    nomes_meses_extenso = [
        'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
        'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
    ]
    nome_mes_atual = nomes_meses_extenso[mes_atual - 1]

    soma_mensalidades = sum(m.plano.valor for m in matriculas if m.situacao == 'ativa')
    meta_mensal = soma_mensalidades if soma_mensalidades > Decimal('0.00') else Decimal('50000.00')
    faltam_meta = max(Decimal('0.00'), meta_mensal - total_recebido)
    pct_meta = min(100, int((total_recebido / meta_mensal * 100))) if meta_mensal > 0 else 0


    pagamentos_qs = Pagamento.objects.select_related(
        'cobranca__matricula__aluno',
        'cobranca__matricula__plano'
    ).order_by('-data_pagamento', '-id')[:10]

    pagamentos_recentes = []
    for p in pagamentos_qs:
        pagamentos_recentes.append({
            'plano': p.cobranca.matricula.plano.nome if p.cobranca and p.cobranca.matricula and p.cobranca.matricula.plano else 'Plano SheFit',
            'cliente': p.cobranca.matricula.aluno.nome if p.cobranca and p.cobranca.matricula and p.cobranca.matricula.aluno else 'Aluna',
            'status': 'Pago',
            'status_class': 'pago',
            'valor': p.valor_pago,
            'data': p.data_pagamento,
        })

    if len(pagamentos_recentes) < 6:
        cobrancas_pendentes = Cobranca.objects.filter(paga=False).select_related(
            'matricula__aluno',
            'matricula__plano'
        ).order_by('-vencimento', '-id')[:6 - len(pagamentos_recentes)]

        for c in cobrancas_pendentes:
            pagamentos_recentes.append({
                'plano': c.matricula.plano.nome if c.matricula and c.matricula.plano else 'Plano SheFit',
                'cliente': c.matricula.aluno.nome if c.matricula and c.matricula.aluno else 'Aluna',
                'status': 'Pendente',
                'status_class': 'pendente',
                'valor': c.valor,
                'data': c.vencimento,
            })

    return {
        'receita_mes': receita_mes,
        'receita_mes_formatada': f"R$ {receita_mes:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'crescimento_pct': crescimento_pct,
        'total_recebido': total_recebido,
        'total_recebido_formatado': f"R$ {total_recebido:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'pct_recebido_previsto': pct_recebido_previsto,
        'a_receber': a_receber,
        'a_receber_formatado': f"R$ {a_receber:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'qtd_a_receber': qtd_a_receber,
        'assinaturas_ativas': assinaturas_ativas,
        'novos_planos_mes': novos_planos_mes,
        'evolucao_meses': evolucao_meses,
        'nome_mes_atual': nome_mes_atual,
        'meta_mensal': meta_mensal,
        'meta_mensal_formatada': f"R$ {meta_mensal:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'faltam_meta': faltam_meta,
        'faltam_meta_formatada': f"R$ {faltam_meta:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'pct_meta': pct_meta,
        'pagamentos_recentes': pagamentos_recentes,
    }


@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def dashboard_financeiro(request):
    """
    Exibe os indicadores financeiros consolidados no Dashboard.
    """
    contexto = obter_metricas_dashboard()
    return render(request, 'financeiro/dashboard.html', contexto)


def _periodo_relatorio(request):
    form = RelatorioPeriodoForm(request.GET or None)
    if form.is_valid():
        return form, form.cleaned_data['inicio'], form.cleaned_data['fim']
    hoje = timezone.localdate()
    return form, hoje.replace(day=1), hoje


@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def relatorios_financeiros(request):
    form, inicio, fim = _periodo_relatorio(request)
    return render(request, 'financeiro/relatorios.html', {
        'form': form,
        'inicio': inicio,
        'fim': fim,
        'faixas': relatorio_inadimplencia(inicio, fim),
        'receita': relatorio_receita(inicio, fim),
    })


@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def exportar_relatorio_inadimplencia(request):
    form, inicio, fim = _periodo_relatorio(request)
    resposta = HttpResponse(content_type='text/csv; charset=utf-8')
    resposta['Content-Disposition'] = 'attachment; filename="inadimplencia.csv"'
    resposta.write('\ufeff')
    escritor = csv.writer(resposta, delimiter=';')
    escritor.writerow(['Faixa', 'Aluna', 'Vencimento', 'Valor', 'Dias de atraso'])
    for faixa in relatorio_inadimplencia(inicio, fim):
        for item in faixa['itens']:
            escritor.writerow([
                faixa['nome'],
                item['aluna'],
                item['cobranca'].vencimento.strftime('%d/%m/%Y'),
                item['valor'],
                item['dias_atraso'],
            ])
    return resposta


@login_required(login_url='entrar')
@perfil_requerido('financeiro')
def listar_planos(request):
    """
    Exibe todos os planos (ativos e inativos) para o gestor financeiro
    com os KPIs calculados diretamente do banco de dados.
    """
    planos = Plano.objects.all().order_by('-ativo', 'nome')

    planos_ativos_count = planos.filter(ativo=True).count()
    periodicidades_count = planos.filter(ativo=True).values('periodicidade').distinct().count()
    if periodicidades_count == 0:
        periodicidades_count = planos.values('periodicidade').distinct().count()

    plano_mensal_inicial = planos.filter(ativo=True, periodicidade='mensal').order_by('valor').first()
    if not plano_mensal_inicial:
        plano_mensal_inicial = planos.filter(ativo=True).order_by('valor').first()
    ticket_inicial = plano_mensal_inicial.valor if plano_mensal_inicial else Decimal('0.00')

    form = PlanoForm()

    contexto = {
        'planos': planos,
        'planos_ativos_count': planos_ativos_count,
        'periodicidades_count': periodicidades_count,
        'ticket_inicial': ticket_inicial,
        'form': form,
    }
    return render(request, 'financeiro/listar_planos.html', contexto)


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
@require_POST
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

@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def trancar_matricula_view(request, matricula_id):
    matricula = get_object_or_404(
        Matricula.objects.select_related('aluno', 'plano'), pk=matricula_id,
    )
    form = TrancamentoForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        dados = form.cleaned_data
        try:
            resultado = trancar_matricula(
                matricula, dados['data_inicio'], dados['data_fim'],
                motivo=dados['motivo'], usuario=request.user,
            )
        except ValidationError as erro:
            for mensagem in erro.messages:
                form.add_error(None, mensagem)
        else:
            messages.success(
                request,
                f"Matrícula trancada por {resultado['trancamento'].dias} dia(s). "
                f"{resultado['cobrancas_suspensas']} cobrança(s) suspensa(s) "
                f"e vigência prorrogada.",
            )
            return redirect('historico_trancamentos', matricula_id=matricula.pk)

    return render(request, 'recepcao/trancar_matricula.html', {
        'matricula': matricula, 'form': form,
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def historico_trancamentos(request, matricula_id):
    matricula = get_object_or_404(
        Matricula.objects.select_related('aluno', 'plano'), pk=matricula_id,
    )
    hoje = timezone.localdate()
    itens = []
    for t in matricula.trancamentos.prefetch_related('cobrancas_suspensas'):
        if t.data_fim and t.data_fim <= hoje:
            estado = 'Encerrado'
        elif t.data_inicio > hoje:
            estado = 'Agendado'
        else:
            estado = 'Em curso'
        itens.append({'t': t, 'estado': estado, 'suspensas': t.cobrancas_suspensas.count()})

    return render(request, 'recepcao/historico_trancamentos.html', {
        'matricula': matricula, 'itens': itens, 'total_dias': dias_trancados(matricula),
    })


@login_required(login_url='entrar')
@perfil_requerido('recepcao')
def historico_geral_trancamentos(request):
    hoje = timezone.localdate()
    itens = []
    trancamentos = Trancamento.objects.select_related(
        'matricula__aluno', 'matricula__plano',
    ).prefetch_related('cobrancas_suspensas').order_by('-data_inicio', '-id')
    for trancamento in trancamentos:
        if trancamento.data_fim and trancamento.data_fim <= hoje:
            estado = 'Encerrado'
        elif trancamento.data_inicio > hoje:
            estado = 'Agendado'
        else:
            estado = 'Em curso'
        itens.append({
            't': trancamento,
            'estado': estado,
            'suspensas': trancamento.cobrancas_suspensas.count(),
        })

    return render(request, 'recepcao/historico_geral_trancamentos.html', {
        'itens': itens,
    })
