"""Regras do agendamento de aulas (T11).

O ponto crítico é a ÚLTIMA VAGA. Conferir "tem vaga?" e depois gravar não
resolve: entre uma coisa e outra, outra pessoa pode gravar. Por isso toda
operação que mexe em vagas começa travando a linha da turma no banco
(SELECT ... FOR UPDATE). Quem chega depois espera o primeiro terminar e só
então conta as vagas, já com o resultado dele. Quem trava é o PostgreSQL,
não o Python.
"""
import re
import unicodedata

from django.db import IntegrityError, transaction
from django.utils import timezone

from financeiro.models import Matricula, SituacaoMatricula
from financeiro.servicos import calcular_situacao
from turmas.models import Turma

from .models import Agendamento

Status = Agendamento.Status

# Inadimplente ainda agenda (a recepção também deixa entrar, com aviso — T09).
SITUACOES_QUE_PODEM_AGENDAR = (SituacaoMatricula.ATIVA, SituacaoMatricula.INADIMPLENTE)

MENSAGEM_POR_SITUACAO = {
    SituacaoMatricula.BLOQUEADA: (
        'Sua matrícula está bloqueada por atraso no pagamento. '
        'Regularize na recepção para voltar a agendar aulas.'
    ),
    SituacaoMatricula.TRANCADA: 'Sua matrícula está trancada.',
    SituacaoMatricula.CANCELADA: 'Sua matrícula foi cancelada.',
}


class AgendamentoNegado(Exception):
    """Uma regra de negócio impediu a operação. A mensagem pode ser mostrada ao aluno."""


# ---------------------------------------------------------------- plano x modalidade
def _normalizar(texto):
    sem_acento = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sem_acento.casefold()).strip()


def modalidade_esta_no_plano(modalidade, plano):
    """`Plano.modalidades_incluidas` é texto livre ("Musculação, Dança, Pilates").

    Compara sem diferenciar acento nem maiúscula e exige a palavra inteira,
    então "Yoga" é achada em "musculacao; YOGA e dança", e "Dança" não é
    achada em "Dançarino". Limitação: "Yoga" também é achada em "Hot Yoga".
    O ideal, no futuro, é trocar o texto por uma relação com Modalidade.
    """
    nome = _normalizar(modalidade.nome)
    if not nome:
        return False
    texto = _normalizar(plano.modalidades_incluidas)
    return re.search(rf'(?<![a-z0-9]){re.escape(nome)}(?![a-z0-9])', texto) is not None


# ---------------------------------------------------------------- quem pode agendar
def matricula_do_aluno(aluno):
    """A matrícula mais recente, a mesma escolha que a recepção (T09) faz."""
    return (Matricula.objects.select_related('plano')
            .filter(aluno=aluno).order_by('-data_inicio', '-id').first())


def verificar_matricula(aluno):
    """Devolve (matricula, motivo). motivo é None quando a matrícula permite agendar."""
    matricula = matricula_do_aluno(aluno)
    if matricula is None:
        return None, 'Você ainda não tem matrícula.'
    situacao = calcular_situacao(matricula)
    if situacao not in SITUACOES_QUE_PODEM_AGENDAR:
        return matricula, MENSAGEM_POR_SITUACAO[situacao]
    return matricula, None


def motivo_para_negar(aluno, turma, checar_duplicidade=True):
    """None = pode agendar. Texto = o motivo da recusa."""
    if not turma.ativo:
        return 'Esta turma não está mais ativa.'
    matricula, motivo = verificar_matricula(aluno)
    if motivo:
        return motivo
    if not modalidade_esta_no_plano(turma.modalidade, matricula.plano):
        return (f'A modalidade {turma.modalidade.nome} não está incluída '
                f'no seu plano ({matricula.plano.nome}).')
    if checar_duplicidade and Agendamento.objects.filter(
        turma=turma, aluno=aluno, status__in=[Status.RESERVADO, Status.ESPERA],
    ).exists():
        return 'Você já está nesta turma (com vaga reservada ou na lista de espera).'
    return None

# ---------------------------------------------------------------- vagas e fila
def _travar_turma(turma_id):
    """Trava só a linha da turma (of=('self',)) até o fim da transação atual."""
    try:
        return (Turma.objects.select_for_update(of=('self',))
                .select_related('modalidade').get(pk=turma_id))
    except Turma.DoesNotExist:
        raise AgendamentoNegado('Turma não encontrada.')


def _vagas_livres(turma):
    ocupadas = turma.agendamentos.filter(status=Status.RESERVADO).count()
    return turma.capacidade_maxima - ocupadas


def _preencher_vagas(turma):
    """Dá as vagas livres a quem espera, na ordem de entrada. Chamar com a turma TRAVADA.

    Quem está na fila mas não pode mais agendar (matrícula bloqueada, trancada,
    cancelada, plano trocado) é pulado e mantém o lugar; não perde a vez.
    """
    livres = _vagas_livres(turma)
    promovidos = []
    if livres <= 0:
        return promovidos
    fila = turma.agendamentos.filter(status=Status.ESPERA).select_related('aluno').order_by('id')
    for agendamento in fila:
        if livres <= 0:
            break
        if motivo_para_negar(agendamento.aluno, turma, checar_duplicidade=False):
            continue
        agendamento.status = Status.RESERVADO
        agendamento.promovido_em = timezone.now()
        agendamento.save(update_fields=['status', 'promovido_em'])
        promovidos.append(agendamento)
        livres -= 1
    return promovidos


# ---------------------------------------------------------------- operações
@transaction.atomic
def agendar(aluno, turma_id):
    """Reserva a vaga se houver; senão põe o aluno no fim da lista de espera."""
    turma = _travar_turma(turma_id)

    motivo = motivo_para_negar(aluno, turma)
    if motivo:
        raise AgendamentoNegado(motivo)

    # Antes de aceitar gente nova, a fila anda: assim ninguém fura a ordem
    # de entrada, nem quando a capacidade da turma foi aumentada.
    _preencher_vagas(turma)

    status = Status.RESERVADO if _vagas_livres(turma) > 0 else Status.ESPERA
    try:
        with transaction.atomic():
            return Agendamento.objects.create(turma=turma, aluno=aluno, status=status)
    except IntegrityError:
        raise AgendamentoNegado('Você já está nesta turma (com vaga reservada ou na lista de espera).')


@transaction.atomic
def cancelar_agendamento(aluno, agendamento_id):
    """O aluno cancela o PRÓPRIO agendamento. Se liberou vaga, o próximo da fila a recebe."""
    try:
        turma_id = (Agendamento.objects.values_list('turma_id', flat=True)
                    .get(pk=agendamento_id, aluno=aluno))
    except Agendamento.DoesNotExist:
        raise AgendamentoNegado('Agendamento não encontrado.')

    turma = _travar_turma(turma_id)
    agendamento = Agendamento.objects.get(pk=agendamento_id)  # relido já com a turma travada
    if agendamento.status == Status.CANCELADO:
        raise AgendamentoNegado('Este agendamento já foi cancelado.')

    agendamento.status = Status.CANCELADO
    agendamento.cancelado_em = timezone.now()
    agendamento.save(update_fields=['status', 'cancelado_em'])

    promovidos = _preencher_vagas(turma)
    return agendamento, promovidos