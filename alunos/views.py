from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.core.exceptions import ValidationError
from django.http import JsonResponse
import json

from accounts.models import Perfil
from accounts.decorators import perfil_requerido
from financeiro.servicos import realizar_matricula
from .models import Aluno, Anamnese
from .forms import AlunoForm, AnamneseForm, MatriculaForm
# =========================================================
# 1. VIEWS DA API (USADAS PELO NOVO PAINEL EM REACT)
# =========================================================

def api_listar_alunos(request):
    """ Retorna a lista de alunos para o painel React usando JsonResponse nativo """
    if request.method == 'GET':
        alunos_db = Aluno.objects.all().order_by('-id')
        dados = []
        
        for aluno in alunos_db:
            dados.append({
                'id': aluno.id,
                'name': aluno.nome,
                'email': aluno.email,
                'phone': aluno.telefone,
                'status': 'Ativo' if getattr(aluno, 'ativo', False) else 'Congelado',
                # Caso o plano ou data de entrada venham de outras tabelas, ajuste aqui:
                'plan': 'Básico', 
                'joined': '01/01/2024' 
            })
            
        return JsonResponse(dados, safe=False)

@transaction.atomic 
def api_salvar_aluno(request):
    """ Salva um novo aluno ou edita um existente recebendo JSON do React """
    if request.method in ['POST', 'PUT']:
        try:
            # Lemos o corpo da requisição que o React enviou e convertemos de JSON para Dicionário Python
            dados = json.loads(request.body)

            if request.method == 'POST':
                # 1. Cria o usuário de acesso
                user = User.objects.create_user(
                    username=dados.get('username'),
                    password=dados.get('password'),
                    email=dados.get('email'),
                    first_name=dados.get('name', '').split()[0]
                )

                # 2. Cria o perfil
                perfil = Perfil.objects.create(
                    usuario=user,
                    tipo=Perfil.ALUNO
                )

                # 3. Cria o Aluno
                aluno = Aluno.objects.create(
                    perfil=perfil,
                    nome=dados.get('name'),
                    cpf=dados.get('cpf'),
                    data_nascimento=dados.get('birthDate'),
                    endereco=dados.get('address'),
                    telefone=dados.get('phone'),
                    email=dados.get('email'),
                    contato_emergencia_nome=dados.get('emergencyName'),
                    contato_emergencia_telefone=dados.get('emergencyPhone'),
                    ativo=False
                )

                # 4. Cria a Anamnese
                autorizado = dados.get('authorization', False)
                Anamnese.objects.create(
                    aluno=aluno,
                    restricoes_medicas=dados.get('restrictions', ''),
                    historico_lesoes=dados.get('injuries', ''),
                    condicoes_cronicas=dados.get('conditions', ''),
                    autorizacao_atividade_fisica=autorizado
                )

                if autorizado:
                    aluno.ativo = True
                    aluno.save()

                return JsonResponse({"mensagem": "Aluno cadastrado com sucesso!"}, status=201)

            elif request.method == 'PUT':
                aluno_id = dados.get('id')
                aluno = Aluno.objects.get(id=aluno_id)
                
                aluno.nome = dados.get('name', aluno.nome)
                aluno.telefone = dados.get('phone', aluno.telefone)
                aluno.email = dados.get('email', aluno.email)
                aluno.save()

                if hasattr(aluno, 'anamnese'):
                    aluno.anamnese.restricoes_medicas = dados.get('restrictions', aluno.anamnese.restricoes_medicas)
                    aluno.anamnese.historico_lesoes = dados.get('injuries', aluno.anamnese.historico_lesoes)
                    aluno.anamnese.condicoes_cronicas = dados.get('conditions', aluno.anamnese.condicoes_cronicas)
                    aluno.anamnese.autorizacao_atividade_fisica = dados.get('authorization', aluno.anamnese.autorizacao_atividade_fisica)
                    aluno.anamnese.save()

                return JsonResponse({"mensagem": "Aluno atualizado com sucesso!"}, status=200)

        except Exception as e:
            return JsonResponse({"erro": str(e)}, status=400)
            
    return JsonResponse({"erro": "Método não permitido."}, status=405)


# =========================================================
# 2. VIEWS ANTIGAS (MANTIDAS POR SEGURANÇA E PARA OUTROS PERFIS)
# =========================================================

@login_required
@perfil_requerido('recepcao')
def cadastrar_aluno(request):
    if request.method == 'POST':
        form = AlunoForm(request.POST, request.FILES)
        if form.is_valid():
            # Cria User + Perfil + Aluno (inativo até a anamnese ser autorizada)
            aluno = form.save()
            
            messages.info(
                request, 
                'Cadastro inicial realizado! O aluno só será matriculado e ativado após o preenchimento da anamnese médica e aceite do termo de aptidão física.'
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

    return render(request, 'alunos/editar_aluno.html', {
        'form': form,
        'aluno': aluno
    })


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
    