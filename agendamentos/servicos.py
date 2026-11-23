import re
import unicodedata

from django.db import IntegrityError, transaction
from django.utils import timezone

from financeiro.models import Matricula, SituacaoMatricula
from financeiro.servicos import calcular_situacao
from turmas.models import Turma

from .models import Agendamento

Status = Agendamento.Status


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



def _normalizar(texto):
    sem_acento = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sem_acento.casefold()).strip()


def modalidade_esta_no_plano(modalidade, plano):
    """Verifica se a modalidade está incluída no plano da aluna.

    Suporta:
    1. Relação ManyToMany com Modalidade no modelo Plano (se houver).
    2. Campo texto modalidades_incluidas:
       - Expressões abrangentes como 'Todas as modalidades', 'Todas', 'Acesso total', 'Livre'.
       - Correspondência exata da modalidade inteira como palavra no texto.
       - Correspondência flexível por palavras-chave / nomes parciais (ex.: 'Dança' em
         'Ritmos & Dança', 'Pilates' em 'Pilates Solo', ou 'Ritmos & Dança' para 'Dança').
    """
    if not modalidade or not plano:
        return False

    # 1. Relação ManyToMany com Modalidade se houver no modelo Plano
    if hasattr(plano, 'modalidades'):
        try:
            m2m = getattr(plano, 'modalidades')
            if hasattr(m2m, 'filter'):
                pk = getattr(modalidade, 'pk', None)
                if pk and m2m.filter(pk=pk).exists():
                    return True
        except Exception:
            pass

    try:
        for field in getattr(plano._meta, 'many_to_many', []):
            if getattr(field, 'related_model', None) and field.related_model.__name__ == 'Modalidade':
                m2m_field = getattr(plano, field.name, None)
                pk = getattr(modalidade, 'pk', None)
                if m2m_field and pk and m2m_field.filter(pk=pk).exists():
                    return True
    except Exception:
        pass

    # 2. Campo texto modalidades_incluidas
    texto_raw = getattr(plano, 'modalidades_incluidas', '') or ''
    nome_raw = getattr(modalidade, 'nome', '') or ''
    texto = _normalizar(texto_raw)
    nome = _normalizar(nome_raw)

    if not nome or not texto:
        return False

    # 2.1. Textos abrangentes como "Todas as modalidades", "Todas", "Acesso total", etc.
    padroes_todas = [
        r'\btodas?\s+(as?\s+)?modalidades?\b',
        r'\btodas?\s+(as?\s+)?aulas?\b',
        r'\bacesso\s+total\b',
        r'\blivre\b',
        r'^todas?$',
    ]
    if any(re.search(p, texto) for p in padroes_todas):
        return True

    # 2.2. Modalidade inteira contida como palavra no texto do plano
    if re.search(rf'(?<![a-z0-9]){re.escape(nome)}(?![a-z0-9])', texto):
        return True

    # 2.3. Cruzamento flexível por itens / nomes parciais
    entradas = [e.strip() for e in re.split(r'[,;/\n+]|\s+e\s+', texto) if e.strip()]
    for entrada in entradas:
        if not entrada:
            continue
        # Igualdade direta
        if entrada == nome:
            return True
        # Entrada do plano contida como palavra inteira no nome da modalidade
        # Ex: "danca" contida em "ritmos & danca", "pilates" em "pilates solo"
        if len(entrada) >= 3 and re.search(rf'(?<![a-z0-9]){re.escape(entrada)}(?![a-z0-9])', nome):
            return True
        # Nome da modalidade contido como palavra inteira na entrada do plano
        # Ex: "danca" contida em "aulas de danca"
        if len(nome) >= 3 and re.search(rf'(?<![a-z0-9]){re.escape(nome)}(?![a-z0-9])', entrada):
            return True

    return False



def matricula_do_aluno(aluno):
    """Considera o plano da matrícula mais recente/ativa da aluna."""
    if aluno is None:
        return None
    matriculas = list(
        Matricula.objects.select_related('plano')
        .filter(aluno=aluno)
        .order_by('-data_inicio', '-id')
    )
    for m in matriculas:
        if m.situacao in SITUACOES_QUE_PODEM_AGENDAR:
            return m
    return matriculas[0] if matriculas else None


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



@transaction.atomic
def agendar(aluno, turma_id):
    """Reserva a vaga se houver; senão põe o aluno no fim da lista de espera."""
    turma = _travar_turma(turma_id)

    motivo = motivo_para_negar(aluno, turma)
    if motivo:
        raise AgendamentoNegado(motivo)



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
    agendamento = Agendamento.objects.get(pk=agendamento_id)
    if agendamento.status == Status.CANCELADO:
        raise AgendamentoNegado('Este agendamento já foi cancelado.')

    agendamento.status = Status.CANCELADO
    agendamento.cancelado_em = timezone.now()
    agendamento.save(update_fields=['status', 'cancelado_em'])

    promovidos = _preencher_vagas(turma)
    return agendamento, promovidos
