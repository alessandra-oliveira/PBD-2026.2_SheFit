from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as autenticar_sessao, logout as encerrar_sessao
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Sum

from alunos.models import Aluno
from accounts.models import Perfil
from treinos.models import FichaTreino
from django.utils import timezone
from turmas.models import Turma, Modalidade
from financeiro.models import Plano, Matricula, Cobranca, SituacaoMatricula
from financeiro.servicos import obter_total_meses_periodicidade


def _tipo_do_usuario(usuario):
    """Tipo do perfil, ou None se o usuário não tem perfil (ex.: superusuário do admin)."""
    perfil = getattr(usuario, 'perfil', None)
    return getattr(perfil, 'tipo', None)


def entrar(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        usuario = authenticate(username=username, password=password)

        if usuario is None:  # login incorreto, com erro genérico
            return render(request, 'accounts/login.html', {
                'erro': 'Usuário ou senha inválidos'
            })

        if not hasattr(usuario, 'perfil'):  # logou certo mas não tem perfil
            return render(request, 'accounts/login.html', {
                'erro': 'Usuário sem perfil atribuído.'
            })

        autenticar_sessao(request, usuario)  # usuário loga

        return redirect('painel')  # direciona o navegador para a url painel

    return render(request, 'accounts/login.html')


def sair(request):
    encerrar_sessao(request)  # desloga o usuário
    return redirect('entrar')  # volta para a tela de login


# Redireciona cada um para o seu painel de acordo com o tipo
@login_required(login_url='entrar')
def painel(request):
    tipo = _tipo_do_usuario(request.user)

    if tipo == 'aluno':
        return redirect('painel_aluno')
    elif tipo == 'professor':
        return redirect('painel_professor')
    elif tipo == 'recepcao':
        return redirect('painel_recepcao')
    elif tipo == 'financeiro':
        return redirect('painel_financeiro')
    else:
        raise PermissionDenied  # bloqueia se não tiver tipo válido


# Telas de cada perfil, só entra quem tem o tipo certo
@login_required(login_url='entrar')
def painel_aluno(request):
    if not hasattr(request.user, 'perfil') or request.user.perfil.tipo != 'aluno':
        raise PermissionDenied

    aluno = getattr(request.user.perfil, 'aluno', None)
    ficha_ativa = None
    if aluno:
        ficha_ativa = (
            FichaTreino.objects.filter(aluno=aluno, ativa=True)
            .prefetch_related('exercicios')
            .first()
        )

    return render(request, 'accounts/painel_aluno.html', {
        'aluno': aluno,
        'ficha_ativa': ficha_ativa,
    })


@login_required(login_url='entrar')
def painel_professor(request):
    if not hasattr(request.user, 'perfil') or request.user.perfil.tipo != 'professor':
        raise PermissionDenied
    fichas_revisao_pendente = (
        FichaTreino.objects.filter(ativa=True, data_revisao__lt=timezone.localdate())
        .select_related('aluno')
        .order_by('data_revisao', 'aluno__nome')
    )
    return render(request, 'accounts/painel_professor.html', {
        'fichas_revisao_pendente': fichas_revisao_pendente,
    })


@login_required(login_url='entrar')
def painel_recepcao(request):
    if not hasattr(request.user, 'perfil') or request.user.perfil.tipo != 'recepcao':
        raise PermissionDenied

    hoje = timezone.localdate()

    # 1. Total de estudantes e alunas em atividade
    alunos = Aluno.objects.select_related('perfil').all().order_by('-id')
    total_estudantes = alunos.count()
    estudantes_ativos = alunos.filter(ativo=True).count()
    taxa_atividade = round(
        (estudantes_ativos / total_estudantes * 100), 1) if total_estudantes > 0 else 0

    # 2. Total de aulas / turmas ativas
    total_aulas_ativas = Turma.objects.filter(ativo=True).count()

    # 3. Cadastros mensais nos últimos 6 meses (com altura percentual para o gráfico de barras)
    meses_pt = {
        1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
        7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
    }
    cadastros_mensais = []
    max_cadastros = 0
    for i in range(5, -1, -1):
        data_ref = hoje - relativedelta(months=i)
        qtd = Aluno.objects.filter(
            criado_em__year=data_ref.year, criado_em__month=data_ref.month).count()
        if qtd > max_cadastros:
            max_cadastros = qtd
        cadastros_mensais.append({
            'mes': meses_pt[data_ref.month],
            'ano': data_ref.year,
            'quantidade': qtd,
            'is_atual': (i == 0)
        })
    for item in cadastros_mensais:
        item['altura_pct'] = max(
            int((item['quantidade'] / max_cadastros) * 100), 8) if max_cadastros > 0 else 8

    # 4. Distribuição de matrículas por plano
    paleta_cores = ['#7c3aed', '#ec4899', '#3b82f6',
                    '#10b981', '#f59e0b', '#06b6d4', '#8b5cf6']
    planos_db = Plano.objects.filter(ativo=True)
    total_matriculados = Matricula.objects.count()
    distribuicao_planos = []
    for idx, plano in enumerate(planos_db):
        qtd = Matricula.objects.filter(plano=plano).count()
        pct = round((qtd / total_matriculados * 100),
                    1) if total_matriculados > 0 else 0
        distribuicao_planos.append({
            'id': plano.id,
            'nome': plano.nome,
            'periodicidade': plano.get_periodicidade_display(),
            'quantidade': qtd,
            'porcentagem': pct,
            'cor': paleta_cores[idx % len(paleta_cores)]
        })

    # 5. Aulas populares / frequência por modalidade
    modalidades = Modalidade.objects.all()
    aulas_populares = []
    for mod in modalidades:
        turmas_mod = Turma.objects.filter(modalidade=mod, ativo=True)
        count = turmas_mod.count()
        capacidade_total = turmas_mod.aggregate(Sum('capacidade_maxima'))[
            'capacidade_maxima__sum'] or 0
        pct = round(count / total_aulas_ativas *
                    100) if total_aulas_ativas > 0 else 0
        aulas_populares.append({
            'id': mod.id,
            'nome': mod.nome.strip(),
            'turmas_count': count,
            'capacidade_total': capacidade_total,
            'porcentagem': int(pct)
        })
    aulas_populares.sort(key=lambda x: x['turmas_count'], reverse=True)

    # 6. Agenda da semana (turmas ativas ordenadas por dia e horário)
    dias_ordem = {'segunda': 1, 'terca': 2, 'quarta': 3,
                  'quinta': 4, 'sexta': 5, 'sabado': 6, 'domingo': 7}
    turmas_ativas = Turma.objects.filter(
        ativo=True).select_related('modalidade', 'professor')
    agenda_semana = []
    for t in turmas_ativas:
        nome_prof = (
            t.professor.get_full_name() or t.professor.first_name or t.professor.username
            if t.professor else 'Sem professor'
        )
        hora_str = t.horario.strftime('%H:%M') if t.horario else '--:--'
        hora_fim = (datetime.combine(hoje, t.horario) + timedelta(hours=1)
                    ).strftime('%H:%M') if t.horario else '--:--'
        matriculados = t.capacidade_maxima - t.vagas_restantes()
        agenda_semana.append({
            'id': t.id,
            'modalidade': t.modalidade.nome if t.modalidade else 'Aula',
            'dia': t.get_dia_semana_display(),
            'ordem_dia': dias_ordem.get(t.dia_semana, 99),
            'horario': f'{hora_str} - {hora_fim}',
            'sala': t.sala,
            'professor': nome_prof,
            'capacidade': t.capacidade_maxima,
            'matriculados': matriculados,
            'ocupacao': f'{matriculados}/{t.capacidade_maxima}'
        })
    agenda_semana.sort(key=lambda x: (x['ordem_dia'], x['horario']))

    # 7. Inadimplência do dia (cobranças vencidas não pagas)
    try:
        inadimplentes_hoje = Cobranca.objects.filter(
            paga=False, vencimento__lte=hoje).select_related('matricula__aluno')
    except Exception:
        inadimplentes_hoje = []

    contexto = {
        'alunos': alunos,
        'total_alunos': total_estudantes,
        'total_estudantes': total_estudantes,
        'estudantes_ativos': estudantes_ativos,
        'taxa_atividade': taxa_atividade,
        'total_aulas_ativas': total_aulas_ativas,
        'cadastros_mensais': cadastros_mensais,
        'distribuicao_planos': distribuicao_planos,
        'total_matriculados': total_matriculados,
        'aulas_populares': aulas_populares,
        'agenda_semana': agenda_semana,
        'inadimplentes_hoje': inadimplentes_hoje,
    }

    return render(request, 'accounts/painel_recepcao.html', contexto)


@login_required(login_url='entrar')
def painel_financeiro(request):
    if not hasattr(request.user, 'perfil') or request.user.perfil.tipo != 'financeiro':
        raise PermissionDenied
    return render(request, 'accounts/painel_financeiro.html')


@login_required(login_url='entrar')
def gestao_estudantes_view(request):
    """
    Tela de Gestão de Estudantes (Alunas Cadastradas).
    Disponibiliza métricas gerais e listagem completa com dados de matrícula e plano.
    """
    hoje = timezone.localdate()

    alunos = Aluno.objects.all().select_related('perfil').prefetch_related(
        'matricula_set__plano',
        'matricula_set__cobrancas',
    ).order_by('-id')

    total_estudantes = alunos.count()
    estudantes_ativos = Aluno.objects.filter(ativo=True).count()

    planos_expirados = 0

    for aluno in alunos:
        matriculas = list(aluno.matricula_set.all())
        matricula_recente = (
            sorted(matriculas, key=lambda m: (
                m.data_inicio, m.id), reverse=True)[0]
            if matriculas else None
        )

        aluno.matricula = matricula_recente
        aluno.plano = matricula_recente.plano if matricula_recente else None

        tem_plano_expirado = False
        if matricula_recente:
            # 1. Cobranças vencidas e não pagas
            cobrancas_vencidas = any(
                not c.paga and c.vencimento and c.vencimento < hoje
                for c in matricula_recente.cobrancas.all()
            )

            # 2. Período do plano encerrado
            periodo_expirado = False
            if matricula_recente.plano and matricula_recente.data_inicio:
                meses = obter_total_meses_periodicidade(
                    matricula_recente.plano.periodicidade)
                data_fim = matricula_recente.data_inicio + \
                    relativedelta(months=meses)
                if data_fim < hoje:
                    periodo_expirado = True

            # 3. Situação da matrícula (inadimplente ou bloqueada)
            try:
                situacao = matricula_recente.situacao
                situacao_vencida = situacao in [
                    SituacaoMatricula.INADIMPLENTE, SituacaoMatricula.BLOQUEADA]
            except Exception:
                situacao_vencida = False

            if cobrancas_vencidas or periodo_expirado or situacao_vencida:
                tem_plano_expirado = True
                planos_expirados += 1

        if tem_plano_expirado:
            aluno.status = "Expirado"
        elif aluno.ativo:
            aluno.status = "Ativo"
        else:
            aluno.status = "Inativo"

        aluno.data_entrada = (
            matricula_recente.data_inicio if matricula_recente else aluno.criado_em.date()
        )

    contexto = {
        'total_estudantes': total_estudantes,
        'estudantes_ativos': estudantes_ativos,
        'planos_expirados': planos_expirados,
        'alunos': alunos,
        # Variáveis adicionais de compatibilidade
        'total_alunos': total_estudantes,
        'alunos_ativos': estudantes_ativos,
    }

    return render(request, 'accounts/gestao_estudantes.html', contexto)
