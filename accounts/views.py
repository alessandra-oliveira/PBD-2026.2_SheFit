from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as autenticar_sessao, logout as encerrar_sessao
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import PermissionDenied
from alunos.models import Aluno
from django.http import JsonResponse
from accounts.models import Perfil

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
    if hasattr(request.user, 'perfil') and request.user.perfil.tipo != 'recepcao':
        raise PermissionDenied

    alunos = Perfil.objects.filter(tipo='aluno') 
    
    context = {
        'alunos': alunos, # Passa a lista para o template
    }

    return render(request, 'accounts/painel_recepcao.html')

@login_required(login_url='entrar')
def painel_financeiro(request):
    if request.user.perfil.tipo != 'financeiro':
        raise PermissionDenied
    return render(request, 'accounts/painel_financeiro.html')


def api_listar_professores(request):
    """
    Busca todos os usuários com o perfil de 'professor' e envia para o React em formato JSON.
    """
    # Filtra apenas quem tem o tipo 'professor' e puxa os dados do usuário atrelado
    perfis_professores = Perfil.objects.filter(tipo='professor').select_related('usuario')
    
    dados = []
    for perfil in perfis_professores:
        usuario = perfil.usuario
        nome_bruto = (usuario.get_full_name() or usuario.first_name or usuario.username).strip()
        nome_completo = nome_bruto.title() if nome_bruto else "Professor"
        
        # Gera as iniciais para o ícone (ex: "Mariana Souza" -> "MS")
        partes_nome = nome_completo.split()
        if len(partes_nome) > 1:
            iniciais = (partes_nome[0][0] + partes_nome[-1][0]).upper()
        elif partes_nome:
            iniciais = partes_nome[0][0:2].upper()
        else:
            iniciais = "??"

        dados.append({
            'id': usuario.id,
            'user_id': usuario.id,
            'name': nome_completo,
            'initials': iniciais,
            'email': usuario.email,
            
            # Se você tiver uma tabela separada para Professor (como tem para Aluno),
            # pode ajustar os campos abaixo. Por enquanto, usamos placeholders:
            'phone': '(00) 00000-0000', 
            'status': 'Disponível',
            'experience': 5,
            'rating': '4,8',
            'students': 20,
            'specialties': ['Geral'],
            'weeklyHours': 30,
        })
        
    return JsonResponse(dados, safe=False)

def api_dashboard_recepcao(request):
    """
    Retorna os dados analíticos e operacionais para o Dashboard da Recepção (React):
    - Total de estudantes matriculados, ativos e histórico dos últimos 6 meses
    - Contagem e listagem de aulas/turmas ativas para alimentar a "Agenda do Dia" e métricas
    - Distribuição de planos ativos com quantidades e percentuais
    - Aulas populares por modalidade com taxas de ocupação/frequência
    """
    try:
        from turmas.models import Turma, Modalidade
        from financeiro.models import Plano, Matricula
        from django.utils import timezone
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        from django.db.models import Sum

        hoje = timezone.localtime()

        # 1. Métricas de Estudantes
        total_estudantes = Aluno.objects.count()
        estudantes_ativos = Aluno.objects.filter(ativo=True).count()
        taxa_atividade = round((estudantes_ativos / total_estudantes * 100), 1) if total_estudantes > 0 else 0

        # Histórico de cadastros (últimos 6 meses)
        meses_pt = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun', 7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
        cadastros_mensais = []
        for i in range(5, -1, -1):
            data_ref = hoje - relativedelta(months=i)
            nome_mes = meses_pt[data_ref.month]
            qtd = Aluno.objects.filter(criado_em__year=data_ref.year, criado_em__month=data_ref.month).count()
            cadastros_mensais.append([nome_mes, qtd])

        # 2. Métricas de Turmas e Aulas
        total_aulas_ativas = Turma.objects.filter(ativo=True).count()

        # 3. Distribuição de Planos
        paleta_cores = ['#6f2cf4', '#e843a6', '#1e3a8a', '#10b981', '#f59e0b', '#06b6d4', '#8b5cf6']
        planos_db = Plano.objects.filter(ativo=True)
        total_matriculados = Matricula.objects.filter(status='ATIVA').count()

        distribuicao_planos = []
        for idx, plano in enumerate(planos_db):
            qtd = Matricula.objects.filter(plano=plano, status='ATIVA').count()
            pct = round((qtd / total_matriculados * 100), 1) if total_matriculados > 0 else 0
            distribuicao_planos.append({
                'id': plano.id,
                'nome': plano.nome,
                'quantidade': qtd,
                'porcentagem': pct,
                'cor': paleta_cores[idx % len(paleta_cores)]
            })

        # Fallback caso não haja planos cadastrados
        if not distribuicao_planos:
            distribuicao_planos = [
                {'id': 1, 'nome': 'Padrão', 'quantidade': total_estudantes, 'porcentagem': 100.0, 'cor': '#6f2cf4'}
            ]

        # 4. Agenda do Dia / Próximas Aulas
        dias_semana_codigo = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        dia_hoje = dias_semana_codigo[hoje.weekday()]

        turmas_qs = Turma.objects.filter(ativo=True).select_related('modalidade', 'professor')
        turmas_hoje = turmas_qs.filter(dia_semana=dia_hoje).order_by('horario')

        is_hoje = turmas_hoje.exists()
        turmas_agenda = turmas_hoje if is_hoje else turmas_qs.order_by('dia_semana', 'horario')[:6]

        agenda_dia = []
        for t in turmas_agenda:
            matriculados = t.capacidade_maxima - t.vagas_restantes()
            nome_prof = t.professor.get_full_name() or t.professor.first_name or t.professor.username if t.professor else "Sem professor"
            hora_str = t.horario.strftime('%H:%M')
            hora_fim = (datetime.combine(hoje.date(), t.horario) + timedelta(hours=1)).strftime('%H:%M')

            agenda_dia.append({
                'id': t.id,
                'nome': t.modalidade.nome.strip() if t.modalidade else "Aula",
                'horario': f"{hora_str} – {hora_fim}",
                'dia': t.get_dia_semana_display(),
                'dia_codigo': t.dia_semana,
                'sala': t.sala,
                'professor': nome_prof,
                'capacidade': t.capacidade_maxima,
                'matriculados': matriculados,
                'ocupacao': f"{matriculados}/{t.capacidade_maxima}"
            })

        # 5. Aulas Populares por Modalidade
        modalidades = Modalidade.objects.all()
        aulas_populares = []
        for mod in modalidades:
            turmas_mod = Turma.objects.filter(modalidade=mod, ativo=True)
            count = turmas_mod.count()
            capacidade_total = turmas_mod.aggregate(Sum('capacidade_maxima'))['capacidade_maxima__sum'] or 0
            frequencia = round(count / total_aulas_ativas, 2) if total_aulas_ativas > 0 else 0.0

            aulas_populares.append({
                'id': mod.id,
                'nome': mod.nome.strip(),
                'turmas_count': count,
                'capacidade_total': capacidade_total,
                'frequencia': frequencia,
                'porcentagem': int(frequencia * 100)
            })

        aulas_populares.sort(key=lambda x: x['turmas_count'], reverse=True)

        return JsonResponse({
            'total_estudantes': total_estudantes,
            'estudantes_ativos': estudantes_ativos,
            'taxa_atividade': taxa_atividade,
            'cadastros_mensais': cadastros_mensais,
            'total_aulas_ativas': total_aulas_ativas,
            'total_matriculados': total_matriculados if total_matriculados > 0 else total_estudantes,
            'distribuicao_planos': distribuicao_planos,
            'agenda_dia': agenda_dia,
            'aulas_populares': aulas_populares,
            'is_hoje': is_hoje
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def api_usuario_atual(request):
    """
    Retorna os dados do usuário autenticado na sessão atual para o React.
    """
    if not request.user.is_authenticated:
        return JsonResponse({
            'autenticado': False,
            'id': None,
            'username': 'recepcao',
            'nome': 'Recepção',
            'email': '',
            'tipo': 'recepcao',
            'tipo_display': 'Recepção',
            'iniciais': 'RC'
        })

    usuario = request.user
    perfil = getattr(usuario, 'perfil', None)
    tipo = getattr(perfil, 'tipo', 'recepcao')
    tipo_display = perfil.get_tipo_display() if perfil else 'Recepção'
    nome_bruto = (usuario.get_full_name() or usuario.first_name or usuario.username).strip()
    nome_completo = nome_bruto.title() if nome_bruto else "Recepção"

    partes = nome_completo.split()
    if len(partes) > 1:
        iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif partes:
        iniciais = partes[0][:2].upper()
    else:
        iniciais = "RC"

    return JsonResponse({
        'autenticado': True,
        'id': usuario.id,
        'username': usuario.username,
        'nome': nome_completo,
        'email': usuario.email,
        'tipo': tipo,
        'tipo_display': tipo_display,
        'iniciais': iniciais
    })


@csrf_exempt
def api_sair(request):
    """
    Desloga o usuário da sessão Django e retorna confirmação para o React.
    """
    if request.user.is_authenticated:
        encerrar_sessao(request)
    return JsonResponse({'status': 'success', 'redirect': '/entrar/'})
