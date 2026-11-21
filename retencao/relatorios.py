from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Max, Q
from django.utils import timezone

from financeiro.models import Matricula, SituacaoMatricula
from financeiro.servicos import calcular_situacao, fim_vigencia
from recepcao.models import Frequencia as Entrada
from turmas.models import Frequencia as PresencaAula, Turma

from .servicos import PERIODO_PADRAO, PERIODOS

MINIMO_SEMANAL_ANTERIOR = Decimal('1')   # "vinha": ao menos 1 dia/semana no período anterior
LIMITE_QUEDA = Decimal('0.5')            # "parou": caiu 50% ou mais
MINIMO_DIAS_DE_MATRICULA = 7             # menos que isso não dá base para dizer "vinha"
LIMITE_PERIODO_PERSONALIZADO_DIAS = 366
PERIODO_PERSONALIZADO = 'personalizado'


def _uma_casa(valor):
    return valor.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

def _percentual(parte, total):
    if not total:
        return None          # sem base: None, nunca um 0% enganoso
    return _uma_casa(Decimal(parte) * 100 / Decimal(total))

def _por_semana(dias_com_acesso, dias_de_matricula):
    return _uma_casa(Decimal(dias_com_acesso) * 7 / Decimal(dias_de_matricula))


@dataclass(frozen=True)
class Periodo:
    chave: str
    rotulo: str
    inicio: date
    fim: date

    @property
    def dias(self):
        return (self.fim - self.inicio).days + 1

    def anterior(self):
        """Período imediatamente antes, do mesmo tamanho: a base de comparação do risco."""
        fim = self.inicio - timedelta(days=1)
        return Periodo('anterior', 'Período anterior', fim - timedelta(days=self.dias - 1), fim)

    def parametros(self):
        if self.chave == PERIODO_PERSONALIZADO:
            return {'periodo': self.chave, 'de': self.inicio.isoformat(), 'ate': self.fim.isoformat()}
        return {'periodo': self.chave}

    @property
    def texto(self):
        return f'{self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y}'


def _data(valor):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


def resolver_periodo(chave=None, de=None, ate=None, hoje=None):
    """Converte a URL num Periodo. Devolve (periodo, erro). Parâmetro inválido nunca
    quebra a tela: cai no padrão (30 dias) e devolve o motivo em `erro`."""
    hoje = hoje or timezone.localdate()
    padrao = _atalho(PERIODO_PADRAO, hoje)

    if chave == PERIODO_PERSONALIZADO or de or ate:
        inicio, fim = _data(de), _data(ate)
        if inicio is None or fim is None:
            return padrao, 'Informe as duas datas do período (início e fim).'
        if inicio > hoje:
            return padrao, 'O início do período não pode ser no futuro.'
        fim = min(fim, hoje)
        if inicio > fim:
            return padrao, 'A data de início não pode ser depois da data de fim.'
        if (fim - inicio).days + 1 > LIMITE_PERIODO_PERSONALIZADO_DIAS:
            return padrao, f'O período pode ter no máximo {LIMITE_PERIODO_PERSONALIZADO_DIAS} dias.'
        return Periodo(PERIODO_PERSONALIZADO, 'Período personalizado', inicio, fim), None

    if chave in PERIODOS:
        return _atalho(chave, hoje), None
    return padrao, None


def _atalho(chave, hoje):
    rotulo, dias = PERIODOS[chave]
    return Periodo(chave, rotulo, hoje - timedelta(days=dias - 1), hoje)


def _limites_datetime(inicio, fim):
    """[00:00 do início, 00:00 do dia seguinte ao fim) no fuso do projeto."""
    fuso = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(inicio, time.min), fuso),
        timezone.make_aware(datetime.combine(fim + timedelta(days=1), time.min), fuso),
    )

def formatar_telefone(telefone):
    digitos = ''.join(c for c in (telefone or '') if c.isdigit())
    if len(digitos) == 11:
        return f'({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}'
    if len(digitos) == 10:
        return f'({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}'
    return telefone or ''


def _dias_de_matricula(matricula, inicio, fim):
    """Dias de [inicio, fim] em que a matrícula esteve em vigor (sem os dias trancada)."""
    comeco = max(inicio, matricula.data_inicio)
    termino = fim
    cancelamento = getattr(matricula, 'cancelamento', None)
    if cancelamento is not None:
        termino = min(termino, cancelamento.data)
    if termino < comeco:
        return 0
    dias = (termino - comeco).days + 1
    for t in matricula.trancamentos.all():
        t_inicio = max(comeco, t.data_inicio)
        t_fim = min(termino, t.data_fim or termino)
        if t_fim >= t_inicio:
            dias -= (t_fim - t_inicio).days + 1
    return max(dias, 0)


def _dias_com_acesso(inicio, fim):
    """{aluno_id: {datas}}. Só entradas LIBERADAS (barrada na catraca não é acesso).
    Conta DIAS, não passagens: duas passagens no mesmo dia é uma visita."""
    ini, fim_dt = _limites_datetime(inicio, fim)
    pares = Entrada.objects.filter(
        liberado=True, data_hora__gte=ini, data_hora__lt=fim_dt,
    ).values_list('aluno_id', 'data_hora')
    dias = defaultdict(set)
    for aluno_id, data_hora in pares:
        dias[aluno_id].add(timezone.localtime(data_hora).date())
    return dias


def _ultimo_acesso_ate(fim):
    _, limite = _limites_datetime(fim, fim)
    linhas = (
        Entrada.objects.filter(liberado=True, data_hora__lt=limite)
        .values('aluno_id').annotate(ultimo=Max('data_hora'))
    )
    return {l['aluno_id']: timezone.localtime(l['ultimo']).date() for l in linhas}


def _contar_no_intervalo(datas, inicio, fim):
    return sum(1 for d in datas if inicio <= d <= fim)


def _melhor_matricula_por_aluno(matriculas, inicio, fim):
    """{aluno_id: (matricula, dias)}. Aluno com duas matrículas sobrepostas não conta dobrado."""
    melhor = {}
    for m in matriculas:
        dias = _dias_de_matricula(m, inicio, fim)
        atual = melhor.get(m.aluno_id)
        if dias > 0 and (atual is None or dias > atual[1]):
            melhor[m.aluno_id] = (m, dias)
    return melhor

def frequencia_media(periodo):
    """Dias com acesso ÷ semanas de matrícula, por aluno. Quem nunca veio entra com zero
    (senão a média só mediria quem já vem). Matriculado há < 7 dias aparece, mas fica
    fora da média: uma semana curta distorce a conta."""
    matriculas = list(
        Matricula.objects.filter(data_inicio__lte=periodo.fim, aluno__ativo=True)
        .filter(Q(cancelamento__isnull=True) | Q(cancelamento__data__gte=periodo.inicio))
        .select_related('aluno', 'plano', 'cancelamento').prefetch_related('trancamentos')
    )
    por_aluno = _melhor_matricula_por_aluno(matriculas, periodo.inicio, periodo.fim)
    acessos = _dias_com_acesso(periodo.inicio, periodo.fim)
    ultimos = _ultimo_acesso_ate(periodo.fim)

    linhas = []
    for aluno_id, (matricula, dias) in por_aluno.items():
        dias_acesso = len(acessos.get(aluno_id, ()))
        linhas.append({
            'aluno': matricula.aluno, 'plano': matricula.plano.nome,
            'dias_de_matricula': dias, 'dias_com_acesso': dias_acesso,
            'media_semanal': _por_semana(dias_acesso, dias),
            'ultimo_acesso': ultimos.get(aluno_id),
            'entra_na_media': dias >= MINIMO_DIAS_DE_MATRICULA,
        })
    linhas.sort(key=lambda l: (l['media_semanal'], l['aluno'].nome.casefold()))

    na_media = [l for l in linhas if l['entra_na_media']]
    media_geral = (
        _uma_casa(sum((l['media_semanal'] for l in na_media), Decimal('0')) / len(na_media))
        if na_media else None
    )
    return {
        'linhas': linhas, 'media_geral': media_geral,
        'alunos_na_media': len(na_media),
        'alunos_fora_da_media': len(linhas) - len(na_media),
        'sem_nenhum_acesso': sum(1 for l in na_media if l['dias_com_acesso'] == 0),
    }

def ocupacao_turmas(periodo):
    """Ocupação = presenças ÷ (capacidade × aulas realizadas), pela chamada do professor.
    Reserva NÃO entra. "Aula realizada" = dia com chamada registrada. Turma sem chamada
    no período fica em branco, nunca 0%."""
    por_aula = (
        PresencaAula.objects.filter(data__gte=periodo.inicio, data__lte=periodo.fim)
        .values('turma_id', 'data')
        .annotate(presentes=Count('id', filter=Q(presente=True)))
    )
    aulas = defaultdict(int)
    presencas = defaultdict(int)
    for linha in por_aula:
        aulas[linha['turma_id']] += 1
        presencas[linha['turma_id']] += linha['presentes']

    turmas = (
        Turma.objects.filter(Q(ativo=True) | Q(pk__in=aulas.keys()))
        .select_related('modalidade', 'professor')
        .order_by('modalidade__nome', 'dia_semana', 'horario', 'pk')
    )
    linhas = []
    vagas_total = presentes_total = 0
    for t in turmas:
        n_aulas = aulas.get(t.pk, 0)
        n_presencas = presencas.get(t.pk, 0)
        vagas = t.capacidade_maxima * n_aulas
        if n_aulas:
            vagas_total += vagas
            presentes_total += n_presencas
        linhas.append({
            'turma': t,
            'rotulo': f'{t.modalidade.nome} — {t.get_dia_semana_display()} {t.horario:%H:%M}',
            'sala': t.sala,
            'professor': t.professor.get_full_name() or t.professor.get_username(),
            'capacidade': t.capacidade_maxima, 'aulas': n_aulas, 'presencas': n_presencas,
            'media_presentes': _uma_casa(Decimal(n_presencas) / n_aulas) if n_aulas else None,
            'ocupacao': _percentual(n_presencas, vagas),
            'ativa': t.ativo,
        })
    return {
        'linhas': linhas,
        'ocupacao_geral': _percentual(presentes_total, vagas_total),
        'turmas_com_chamada': sum(1 for l in linhas if l['aulas']),
        'turmas_sem_chamada': sum(1 for l in linhas if not l['aulas']),
    }

def alunos_em_risco(periodo, hoje=None):
    """Quem vinha e parou de vir. Compara o período escolhido com o anterior (mesmo tamanho).
      - "vinha": no anterior veio ao menos 1 dia/semana (e tinha >= 7 dias de matrícula nele);
      - "parou": a média semanal do período caiu 50% ou mais — inclusive a zero.
    Só quem ainda dá para recuperar: matrícula NÃO cancelada e NÃO trancada."""
    hoje = hoje or timezone.localdate()
    anterior = periodo.anterior()

    matriculas = list(
        Matricula.objects.filter(
            cancelamento__isnull=True, data_inicio__lte=periodo.fim, aluno__ativo=True,
        ).select_related('aluno', 'plano').prefetch_related('trancamentos')
    )
    base = _melhor_matricula_por_aluno(matriculas, anterior.inicio, anterior.fim)
    atuais = _melhor_matricula_por_aluno(matriculas, periodo.inicio, periodo.fim)
    acessos = _dias_com_acesso(anterior.inicio, periodo.fim)
    ultimos = _ultimo_acesso_ate(periodo.fim)

    linhas = []
    for aluno_id, (matricula, dias_ant) in base.items():
        if dias_ant < MINIMO_DIAS_DE_MATRICULA or aluno_id not in atuais:
            continue
        dias_atual = atuais[aluno_id][1]
        datas = acessos.get(aluno_id, ())
        acessos_ant = _contar_no_intervalo(datas, anterior.inicio, anterior.fim)
        acessos_atual = _contar_no_intervalo(datas, periodo.inicio, periodo.fim)

        taxa_ant = Decimal(acessos_ant) * 7 / dias_ant
        taxa_atual = Decimal(acessos_atual) * 7 / dias_atual
        if taxa_ant < MINIMO_SEMANAL_ANTERIOR:
            continue                          # não "vinha": não há o que ter perdido
        if taxa_atual > taxa_ant * (1 - LIMITE_QUEDA):
            continue                          # caiu menos que o limite

        situacao = calcular_situacao(matricula, hoje=hoje)
        if situacao == SituacaoMatricula.TRANCADA:
            continue                          # trancar é pausa combinada, não sumiço

        queda = (1 - taxa_atual / taxa_ant) * 100
        aluno = matricula.aluno
        ultimo = ultimos.get(aluno_id)
        linhas.append({
            'aluno': aluno,
            'telefone': formatar_telefone(aluno.telefone),
            'telefone_digitos': aluno.telefone,
            'email': aluno.email,
            'plano': matricula.plano.nome,
            'situacao': SituacaoMatricula(situacao).label,
            'situacao_codigo': situacao.value,
            'acessos_anterior': acessos_ant, 'acessos_atual': acessos_atual,
            'media_anterior': _uma_casa(taxa_ant), 'media_atual': _uma_casa(taxa_atual),
            'queda': queda,
            'queda_texto': f'{queda.quantize(Decimal("1"), rounding=ROUND_HALF_UP)}%',
            'ultimo_acesso': ultimo,
            'dias_sem_vir': (periodo.fim - ultimo).days if ultimo else None,
            'sumiu': acessos_atual == 0,
        })

    # quem sumiu por completo há mais tempo vem primeiro: está mais perto de cancelar
    linhas.sort(key=lambda l: (
        not l['sumiu'], -(l['dias_sem_vir'] or 0), -l['queda'], l['aluno'].nome.casefold(),
    ))
    return {
        'linhas': linhas, 'anterior': anterior, 'total': len(linhas),
        'sumiram': sum(1 for l in linhas if l['sumiu']),
        'queda_minima_pct': int(LIMITE_QUEDA * 100),
        'minimo_semanal': MINIMO_SEMANAL_ANTERIOR, 'minimo_dias': MINIMO_DIAS_DE_MATRICULA,
    }

class ResultadoRenovacao:
    RENOVOU = 'renovou'
    CANCELOU = 'cancelou'
    SEM_RENOVACAO = 'sem_renovacao'
    ROTULOS = {RENOVOU: 'Renovou', CANCELOU: 'Cancelou', SEM_RENOVACAO: 'Ainda sem renovação'}


def taxa_renovacao(periodo):
    """Taxa = ciclos renovados ÷ ciclos que TERMINARAM no período. Cada fim de ciclo é uma
    "decisão de renovar": renovou (existe o ciclo seguinte), cancelou, ou ainda sem
    renovação (venceu e a recepção ainda pode confirmar — conta CONTRA a taxa de propósito).
    Quem já tinha cancelado ANTES do período não entra: a saída é de outro período."""
    matriculas = (
        Matricula.objects.filter(data_inicio__lte=periodo.fim)
        .select_related('aluno', 'plano', 'cancelamento').prefetch_related('renovacoes')
    )
    linhas = []
    for m in matriculas:
        cancelamento = getattr(m, 'cancelamento', None)
        if cancelamento is not None and cancelamento.data < periodo.inicio:
            continue
        ciclos = sorted(m.renovacoes.all(), key=lambda r: r.ciclo)
        # o ciclo k termina onde o ciclo k+1 começa; o último termina na vigência atual
        fins = [r.inicio for r in ciclos] + [fim_vigencia(m)]
        for indice, fim_ciclo in enumerate(fins):
            if not (periodo.inicio <= fim_ciclo <= periodo.fim):
                continue
            if indice < len(ciclos):
                resultado = ResultadoRenovacao.RENOVOU
            elif cancelamento is not None:
                resultado = ResultadoRenovacao.CANCELOU
            else:
                resultado = ResultadoRenovacao.SEM_RENOVACAO
            linhas.append({
                'aluno': m.aluno, 'telefone': formatar_telefone(m.aluno.telefone),
                'plano': m.plano.nome, 'matricula_id': m.pk,
                'ciclo': indice + 1, 'fim_ciclo': fim_ciclo,
                'resultado': resultado, 'resultado_texto': ResultadoRenovacao.ROTULOS[resultado],
            })
    linhas.sort(key=lambda l: (l['fim_ciclo'], l['aluno'].nome.casefold()))

    def contar(r):
        return sum(1 for l in linhas if l['resultado'] == r)

    return {
        'linhas': linhas, 'base': len(linhas),
        'renovaram': contar(ResultadoRenovacao.RENOVOU),
        'cancelaram': contar(ResultadoRenovacao.CANCELOU),
        'sem_renovacao': contar(ResultadoRenovacao.SEM_RENOVACAO),
        'taxa': _percentual(contar(ResultadoRenovacao.RENOVOU), len(linhas)),
    }


def montar_relatorios(periodo, hoje=None):
    return {
        'frequencia': frequencia_media(periodo),
        'ocupacao': ocupacao_turmas(periodo),
        'risco': alunos_em_risco(periodo, hoje=hoje),
        'renovacao': taxa_renovacao(periodo),
    }


