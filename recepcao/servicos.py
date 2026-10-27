from financeiro.servicos import avaliar_situacao_financeira_aluno
from alunos.models import Aluno
from .models import Frequencia

def processar_entrada_aluno(identificador):
    """
    Processa a entrada do aluno na recepção (por CPF ou Nome) (Tarefa T09).
    """
    # 1. Tenta encontrar o aluno por CPF exato ou por nome parcial
    aluno = Aluno.objects.filter(cpf=identificador).first()
    if not aluno:
        aluno = Aluno.objects.filter(nome__icontains=identificador).first()

    if not aluno:
        return {
            'sucesso': False,
            'mensagem': 'Aluno não encontrado.',
            'aluno': None,
            'resultado_financeiro': None
        }

    # 2. Avalia a situação financeira em tempo real usando o serviço do financeiro
    resultado_financeiro = avaliar_situacao_financeira_aluno(aluno)
    status = resultado_financeiro['status']

    # 3. Define se o acesso é permitido e regista a frequência de acordo com a regra
    if status in ['liberado', 'liberado_com_aviso']:
        obs = "Liberado com aviso de atraso" if status == 'liberado_com_aviso' else "Acesso normal"
        
        # Regista a frequência com data e hora exatas da entrada
        Frequencia.objects.create(
            aluno=aluno,
            liberado=True,
            observacao=obs
        )

        return {
            'sucesso': True,
            'status': status,
            'mensagem': resultado_financeiro['motivo'],
            'detalhes': resultado_financeiro.get('detalhes'),
            'aluno': aluno
        }
    else:
        # Acesso bloqueado (não gera registo de frequência de entrada autorizada)
        return {
            'sucesso': False,
            'status': status,
            'mensagem': resultado_financeiro['motivo'],
            'detalhes': resultado_financeiro.get('detalhes'),
            'aluno': aluno
        }