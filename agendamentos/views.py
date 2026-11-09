from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import perfil_requerido
from turmas.models import Turma

from .models import Agendamento
from .servicos import (
    AgendamentoNegado, agendar, cancelar_agendamento,
    modalidade_esta_no_plano, verificar_matricula,
)

Status = Agendamento.Status
ORDEM_DOS_DIAS = {dia: posicao for posicao, (dia, _) in enumerate(Turma.DIAS_SEMANA)}


def _aluno_logado(request):
    return getattr(request.user.perfil, 'aluno', None)


def _ordenar(turmas):
    return sorted(turmas, key=lambda t: (ORDEM_DOS_DIAS.get(t.dia_semana, 99), t.horario))


@perfil_requerido('aluno')
def minhas_aulas(request):
    aluno = _aluno_logado(request)
    if aluno is None:
        messages.error(request, 'Não encontramos o seu cadastro de aluno. Procure a recepção.')
        return redirect('painel')

    matricula, impedimento = verificar_matricula(aluno)

    meus_ativos = {
        ag.turma_id: ag
        for ag in Agendamento.objects.filter(
            aluno=aluno, status__in=[Status.RESERVADO, Status.ESPERA],
        ).select_related('turma__modalidade', 'turma__professor')
    }

    disponiveis = []
    if matricula is not None:
        turmas = (Turma.objects.filter(ativo=True)
                  .select_related('modalidade', 'professor')
                  .annotate(
                      reservados=Count('agendamentos', filter=Q(agendamentos__status=Status.RESERVADO)),
                      na_fila=Count('agendamentos', filter=Q(agendamentos__status=Status.ESPERA)),
                  ))
        for turma in _ordenar(t for t in turmas if modalidade_esta_no_plano(t.modalidade, matricula.plano)):
            disponiveis.append({
                'turma': turma,
                'vagas': max(turma.capacidade_maxima - turma.reservados, 0),
                'na_fila': turma.na_fila,
                'meu': meus_ativos.get(turma.id),
            })

    minhas_reservas = [
        {'agendamento': ag, 'turma': ag.turma, 'posicao': ag.posicao_na_fila()}
        for ag in sorted(meus_ativos.values(), key=lambda a: (
            ORDEM_DOS_DIAS.get(a.turma.dia_semana, 99), a.turma.horario))
    ]
   
    # a posição na fila também vai para a tabela de turmas; e o resumo do topo conta cada coisa
    posicoes = {item['turma'].id: item['posicao'] for item in minhas_reservas}
    for item in disponiveis:
        item['posicao'] = posicoes.get(item['turma'].id)
    total_reservadas = sum(1 for item in minhas_reservas if item['agendamento'].status == Status.RESERVADO)
   
    return render(request, 'agendamentos/minhas_aulas.html', {
        'aluno': aluno,
        'matricula': matricula,
        'impedimento': impedimento,
        'disponiveis': disponiveis,
        'minhas_reservas': minhas_reservas,
    })


@perfil_requerido('aluno')
@require_POST
def agendar_turma(request, turma_id):
    aluno = _aluno_logado(request)
    if aluno is None:
        messages.error(request, 'Não encontramos o seu cadastro de aluno. Procure a recepção.')
        return redirect('painel')
    try:
        agendamento = agendar(aluno, turma_id)
    except AgendamentoNegado as erro:
        messages.error(request, str(erro))
    else:
        if agendamento.status == Status.RESERVADO:
            messages.success(request, f'Vaga reservada: {agendamento.turma}.')
        else:
            messages.warning(
                request,
                f'A turma está cheia. Você entrou na lista de espera na posição '
                f'{agendamento.posicao_na_fila()}º: {agendamento.turma}.',
            )
    return redirect('minhas_aulas')


@perfil_requerido('aluno')
@require_POST
def cancelar(request, agendamento_id):
    aluno = _aluno_logado(request)
    if aluno is None:
        messages.error(request, 'Não encontramos o seu cadastro de aluno. Procure a recepção.')
        return redirect('painel')
    try:
        agendamento, _promovidos = cancelar_agendamento(aluno, agendamento_id)
    except AgendamentoNegado as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f'Agendamento cancelado: {agendamento.turma}.')
    return redirect('minhas_aulas')