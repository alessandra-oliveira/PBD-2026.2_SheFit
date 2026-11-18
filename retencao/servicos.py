"""Regras da tela "Os números da academia" (T21), sem HTTP e fáceis de testar."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from recepcao.models import Frequencia

from treinos.models import ExecucaoExercicio
from turmas.models import Frequencia as PresencaAula

# chave usada na URL -> (rótulo, quantidade de dias)
PERIODOS = {
    '7': ('Últimos 7 dias', 7),
    '30': ('Últimos 30 dias', 30),
    '90': ('Últimos 3 meses', 90),
    '365': ('Último ano', 365),
}
PERIODO_PADRAO = '30'


def normalizar_periodo(valor):
    """Devolve uma chave válida de PERIODOS (valor desconhecido cai no padrão)."""
    return valor if valor in PERIODOS else PERIODO_PADRAO


def frequencia_no_periodo(aluno, periodo, agora=None):
    """Conta os acessos da aluna no período.

    Só conta entradas efetivamente liberadas (`liberado=True`): uma tentativa
    barrada na recepção não é um acesso.
    """
    rotulo, dias = PERIODOS[normalizar_periodo(periodo)]
    agora = agora or timezone.now()
    desde = agora - timedelta(days=dias)
    total = Frequencia.objects.filter(
        aluno=aluno, liberado=True, data_hora__gte=desde, data_hora__lte=agora,
    ).count()
    media_semanal = (Decimal(total) / (Decimal(dias) / Decimal(7))).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP
    )
    return {
        'rotulo': rotulo,
        'dias': dias,
        'desde': desde,
        'total': total,
        'media_semanal': media_semanal,
    }

def presenca_em_aulas_no_periodo(aluno, periodo, hoje=None):
    """Presença da aluna nas aulas coletivas (chamada feita pelo professor).

    Conta só o que a chamada registrou: `presente=True` é presença e
    `presente=False` é falta. Aula sem chamada não entra na conta.
    """
    rotulo, dias = PERIODOS[normalizar_periodo(periodo)]
    hoje = hoje or timezone.localdate()
    desde = hoje - timedelta(days=dias)
    registros = PresencaAula.objects.filter(
        aluno=aluno.perfil.usuario, data__gte=desde, data__lte=hoje,
    ).select_related('turma__modalidade')

    por_modalidade = {}
    for r in registros:
        item = por_modalidade.setdefault(
            r.turma.modalidade.nome, {'modalidade': r.turma.modalidade.nome, 'presencas': 0, 'faltas': 0},
        )
        item['presencas' if r.presente else 'faltas'] += 1

    presencas = sum(i['presencas'] for i in por_modalidade.values())
    faltas = sum(i['faltas'] for i in por_modalidade.values())
    total = presencas + faltas
    percentual = (
        (Decimal(presencas) * 100 / Decimal(total)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        if total else None
    )
    return {
        'rotulo': rotulo, 'total': total, 'presencas': presencas, 'faltas': faltas,
        'percentual': percentual,
        'por_modalidade': sorted(por_modalidade.values(), key=lambda i: i['modalidade']),
    }


def evolucao_de_carga(aluno):
    """Evolução da carga por exercício, a partir das execuções registradas.

    Agrupa pelo nome do exercício (sem diferenciar maiúsculas), para a série
    continuar quando o professor troca a ficha e o exercício se repete.
    """
    execucoes = (
        ExecucaoExercicio.objects.filter(aluno=aluno)
        .select_related('exercicio')
        .order_by('data', 'pk')
    )
    grupos = {}
    for e in execucoes:
        chave = ' '.join(e.exercicio.nome.split()).casefold()
        grupos.setdefault(chave, {'nome': ' '.join(e.exercicio.nome.split()), 'registros': []})
        grupos[chave]['registros'].append(e)

    resultado = []
    for g in grupos.values():
        regs = g['registros']
        primeira, ultima = regs[0].carga_kg, regs[-1].carga_kg
        resultado.append({
            'nome': g['nome'], 'registros': regs, 'quantidade': len(regs),
            'primeira': primeira, 'ultima': ultima,
            'maior': max(r.carga_kg for r in regs),
            'diferenca': (ultima - primeira) if len(regs) > 1 else None,
        })
    return sorted(resultado, key=lambda g: g['nome'].casefold())