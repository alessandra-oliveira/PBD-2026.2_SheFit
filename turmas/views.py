from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.decorators import perfil_requerido
from .models import Turma, Modalidade
from .forms import TurmaForm, ModalidadeForm
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User


DIAS_SEMANA_MAP = {
    'segunda': 'segunda',
    'segunda-feira': 'segunda',
    'seg': 'segunda',
    'terca': 'terca',
    'terça': 'terca',
    'terca-feira': 'terca',
    'terça-feira': 'terca',
    'ter': 'terca',
    'quarta': 'quarta',
    'quarta-feira': 'quarta',
    'qua': 'quarta',
    'quinta': 'quinta',
    'quinta-feira': 'quinta',
    'qui': 'quinta',
    'sexta': 'sexta',
    'sexta-feira': 'sexta',
    'sex': 'sexta',
    'sabado': 'sabado',
    'sábado': 'sabado',
    'sab': 'sabado',
    'domingo': 'domingo',
    'dom': 'domingo',
}


@login_required
@perfil_requerido('recepcao', 'financeiro', 'professor')
def listar_turmas(request):
    if request.user.perfil.tipo == 'professor':
        # Professor só vê as turmas dele
        turmas = Turma.objects.filter(professor=request.user, ativo=True)
    else:
        # Recepção e financeiro veem todas
        turmas = Turma.objects.filter(ativo=True)

    return render(request, 'turmas/listar_turmas.html', {'turmas': turmas})


@login_required
@perfil_requerido('recepcao', 'financeiro')
def criar_turma(request):
    if request.method == 'POST':
        form = TurmaForm(request.POST)
        if form.is_valid():
            turma = form.save(commit=False)
            turma.full_clean()  # roda o clean() do model também
            turma.save()
            messages.success(request, 'Turma cadastrada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = TurmaForm()

    return render(request, 'turmas/form_turma.html', {'form': form})


@login_required
@perfil_requerido('recepcao', 'financeiro')
def editar_turma(request, turma_id):
    turma = get_object_or_404(Turma, id=turma_id)

    if request.method == 'POST':
        form = TurmaForm(request.POST, instance=turma)
        if form.is_valid():
            turma_editada = form.save(commit=False)
            turma_editada.full_clean()
            turma_editada.save()
            messages.success(request, 'Turma atualizada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = TurmaForm(instance=turma)

    return render(request, 'turmas/form_turma.html', {'form': form, 'turma': turma})


@login_required(login_url='entrar')
@require_POST
@perfil_requerido('recepcao', 'financeiro')
def desativar_turma(request, turma_id):
    # Desativa a turma, sem excluí-la do banco de dados.
    turma = get_object_or_404(Turma, id=turma_id)
    turma.ativo = False
    turma.save()

    messages.success(request, 'Turma desativada.')

    return redirect('listar_turmas')

@login_required
@perfil_requerido('recepcao', 'financeiro')
def criar_modalidade(request):
    if request.method == 'POST':
        form = ModalidadeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Modalidade cadastrada com sucesso.')
            return redirect('listar_turmas')
    else:
        form = ModalidadeForm()

    return render(request, 'turmas/form_modalidade.html', {'form': form})


def api_listar_professores(request):
    # Filtra os utilizadores que são professores através do perfil
    professores = User.objects.filter(perfil__tipo='professor')
    dados = []
    for prof in professores:
        dados.append({
            'id': prof.id,  # ID do User exato que o model Turma espera
            'name': prof.get_full_name() or prof.username
        })
    return JsonResponse(dados, safe=False)


def api_listar_modalidades(request):
    """ Envia as modalidades para o React """
    if request.method == 'GET':
        modalidades = Modalidade.objects.all()
        dados = []
        for mod in modalidades:
            dados.append({
                'id': mod.id,
                'name': mod.nome,
                'description': mod.descricao
            })
        return JsonResponse(dados, safe=False)


def api_listar_turmas(request):
    """ Envia as turmas para o React com IDs e campos normalizados """
    if request.method == 'GET':
        turmas = Turma.objects.select_related('modalidade', 'professor').all()
        dados = []
        
        for t in turmas:
            nome_prof = "Sem professor"
            if t.professor:
                nome_prof = t.professor.get_full_name() or t.professor.first_name or t.professor.username

            matriculados = t.capacidade_maxima - t.vagas_restantes()

            dados.append({
                'id': t.id,
                'modality': t.modalidade.nome if t.modalidade else "",
                'modality_id': t.modalidade.id if t.modalidade else None,
                'day': t.get_dia_semana_display(),
                'day_raw': t.dia_semana,
                'time': t.horario.strftime('%H:%M') if t.horario else "",
                'teacher': nome_prof,
                'teacher_id': t.professor.id if t.professor else None,
                'room': t.sala,
                'capacity': t.capacidade_maxima,
                'enrolled': matriculados, 
                'active': t.ativo
            })
            
        return JsonResponse(dados, safe=False)


@csrf_exempt
def api_criar_modalidade(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            nome = data.get('name') or data.get('nome')
            descricao = data.get('description') or data.get('descricao', '')
            
            if not nome:
                return JsonResponse({'status': 'error', 'message': 'O nome é obrigatório.'}, status=400)
            
            modalidade = Modalidade.objects.create(nome=nome, descricao=descricao)
            return JsonResponse({'status': 'success', 'id': modalidade.id})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Método não permitido.'}, status=405)


@csrf_exempt
def api_criar_turma(request):
    """
    Recebe os dados do React, normaliza os campos (modalidade, professor, dia_semana)
    e cria ou atualiza a Turma com segurança. Suporta POST e PUT.
    """
    if request.method not in ['POST', 'PUT']:
        return JsonResponse({'status': 'error', 'message': 'Método não permitido.'}, status=405)

    try:
        data = json.loads(request.body)
        print("DADOS RECEBIDOS:", data)

        # 1. Normalizar Modalidade (suporta ID numérico, string de ID ou Nome)
        mod_val = data.get('modalidade') or data.get('modality')
        if isinstance(mod_val, dict):
            mod_val = mod_val.get('id') or mod_val.get('name')

        if mod_val is not None and str(mod_val).strip() != "":
            mod_str = str(mod_val).strip()
            if mod_str.isdigit():
                mod_obj = Modalidade.objects.filter(id=int(mod_str)).first()
            else:
                mod_obj = Modalidade.objects.filter(nome__iexact=mod_str).first()
            if mod_obj:
                data['modalidade'] = mod_obj.id

        # 2. Normalizar Professor (suporta ID numérico, objeto ou Nome de User com perfil 'professor')
        prof_val = data.get('professor') or data.get('teacher')
        if isinstance(prof_val, dict):
            prof_val = prof_val.get('id') or prof_val.get('name')

        if prof_val is not None and str(prof_val).strip() != "":
            prof_str = str(prof_val).strip()
            user_prof = None
            if prof_str.isdigit():
                user_prof = User.objects.filter(id=int(prof_str), perfil__tipo='professor').first()

            if not user_prof:
                professores_qs = User.objects.filter(perfil__tipo='professor')
                user_prof = (
                    professores_qs.filter(username__iexact=prof_str).first() or
                    professores_qs.filter(first_name__iexact=prof_str).first()
                )
                if not user_prof:
                    for prof in professores_qs:
                        full_name = prof.get_full_name() or f"{prof.first_name} {prof.last_name}".strip()
                        if full_name.lower() == prof_str.lower():
                            user_prof = prof
                            break

            if user_prof:
                data['professor'] = user_prof.id

        # 3. Normalizar Dia da Semana (remove acentos e padroniza para 'segunda', 'terca', etc.)
        dia_val = data.get('dia_semana') or data.get('day')
        if dia_val is not None:
            dia_str = str(dia_val).strip().lower()
            data['dia_semana'] = DIAS_SEMANA_MAP.get(dia_str, dia_str)

        # 4. Compatibilidade de chaves alternativas (inglês -> português)
        if 'time' in data and 'horario' not in data:
            data['horario'] = data['time']
        if 'room' in data and 'sala' not in data:
            data['sala'] = data['room']
        if 'capacity' in data and 'capacidade_maxima' not in data:
            data['capacidade_maxima'] = data['capacity']

        # 5. Suporte a Edição (caso venha ID da turma)
        turma_id = data.get('id') or data.get('turma_id')
        turma_instance = None
        if turma_id and str(turma_id).isdigit():
            turma_instance = Turma.objects.filter(id=int(turma_id)).first()

        form = TurmaForm(data, instance=turma_instance)
        if form.is_valid():
            turma = form.save(commit=False)
            turma.full_clean()
            turma.save()
            return JsonResponse({
                'status': 'success',
                'message': 'Turma atualizada com sucesso!' if turma_instance else 'Turma criada com sucesso!',
                'id': turma.id
            })
        else:
            print("ERROS DE VALIDAÇÃO DO DJANGO:", form.errors)
            return JsonResponse({'status': 'error', 'errors': form.errors.get_json_data()}, status=400)

    except Exception as e:
        print("EXCEÇÃO:", e)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
