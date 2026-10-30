import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from alunos.models import Aluno
from financeiro.servicos import avaliar_situacao_financeira_aluno
from .models import Frequencia

# Quantas alunas a busca por nome mostra de uma vez.
LIMITE_RESULTADOS_BUSCA = 10

# Duas entradas da mesma aluna dentro desta janela contam como a mesma
# (protege contra clique duplo / reenvio). Ajuste se a regra da academia mudar.
JANELA_ENTRADA_DUPLICADA = timedelta(minutes=10)

STATUS_LIBERADOS = ('liberado', 'liberado_com_aviso')


def buscar_alunos(termo):
    """Identifica alunas por CPF (11 dígitos, com ou sem pontuação) ou por parte
    do nome (Tarefa T09). NUNCA escolhe uma aluna sozinho: devolve todas as
    correspondentes para a recepção confirmar.

    Devolve (lista_de_alunas, truncado). `truncado` indica que havia mais
    resultados que o limite e a busca deve ser refinada.
    """
    termo = (termo or '').strip()
    if not termo:
        return [], False

    digitos = re.sub(r'\D', '', termo)
    if len(digitos) == 11:
        return list(Aluno.objects.filter(cpf=digitos)), False

    encontradas = list(
        Aluno.objects.filter(nome__icontains=termo).order_by('nome')[:LIMITE_RESULTADOS_BUSCA + 1]
    )
    truncado = len(encontradas) > LIMITE_RESULTADOS_BUSCA
    return encontradas[:LIMITE_RESULTADOS_BUSCA], truncado


def avaliar_acesso(aluno):
    """Diz se a aluna pode entrar AGORA. Só consulta: não grava nada."""
    if not aluno.ativo:
        return {
            'sucesso': False,
            'status': 'bloqueado',
            'mensagem': 'Cadastro inativo (anamnese pendente ou aluna desativada).',
            'detalhes': None,
            'aluno': aluno,
        }

    financeiro = avaliar_situacao_financeira_aluno(aluno)
    status = financeiro['status']
    return {
        'sucesso': status in STATUS_LIBERADOS,
        'status': status,
        'mensagem': financeiro['motivo'],
        'detalhes': financeiro.get('detalhes'),
        'aluno': aluno,
    }


def registrar_entrada(aluno):
    """Registra a entrada, mas só se o acesso estiver liberado.

    Reavalia o acesso no momento do registro (não confia em consulta anterior)
    e não duplica a entrada dentro de JANELA_ENTRADA_DUPLICADA.
    """
    resultado = avaliar_acesso(aluno)
    resultado.update(registrada=False, duplicada=False, frequencia=None)
    if not resultado['sucesso']:
        return resultado

    with transaction.atomic():
        # Trava a linha da aluna: dois cliques simultâneos entram um de cada vez.
        Aluno.objects.select_for_update().get(pk=aluno.pk)

        recente = Frequencia.objects.filter(
            aluno=aluno,
            liberado=True,
            data_hora__gte=timezone.now() - JANELA_ENTRADA_DUPLICADA,
        ).first()
        if recente:
            resultado.update(duplicada=True, frequencia=recente)
            return resultado

        observacao = (
            'Liberado com aviso de atraso'
            if resultado['status'] == 'liberado_com_aviso' else 'Acesso normal'
        )
        frequencia = Frequencia.objects.create(
            aluno=aluno, liberado=True, observacao=observacao,
        )

    resultado.update(registrada=True, frequencia=frequencia)
    return resultado


def processar_entrada_aluno(identificador):
    """Busca + registro em uma chamada (uso fora da tela, ex.: scripts/testes).

    Só registra se a busca identificar UMA aluna. Se houver várias, devolve a
    lista em 'candidatos' sem registrar nada.
    """
    alunos, _ = buscar_alunos(identificador)

    if not alunos:
        return {
            'sucesso': False,
            'mensagem': 'Aluno não encontrado.',
            'aluno': None,
            'resultado_financeiro': None,
        }
    if len(alunos) > 1:
        return {
            'sucesso': False,
            'mensagem': 'Mais de um aluno encontrado. Informe o CPF.',
            'aluno': None,
            'candidatos': alunos,
        }
    return registrar_entrada(alunos[0])