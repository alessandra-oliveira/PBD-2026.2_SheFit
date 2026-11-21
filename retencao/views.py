import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.decorators import perfil_requerido
from alunos.models import Aluno
from avaliacoes.servicos import chave_cronologica, comparar_avaliacoes

from . import relatorios
from .servicos import (
    PERIODOS, evolucao_de_carga, frequencia_no_periodo, normalizar_periodo,
    presenca_em_aulas_no_periodo,
)

def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@perfil_requerido('aluno')
def numeros_da_academia(request):
    """Tela de retenção: a aluna vê o quanto veio e o quanto mudou.

    Só mostra os dados da PRÓPRIA aluna logada.
    """
    aluno = get_object_or_404(Aluno, perfil=request.user.perfil)


    periodo = normalizar_periodo(request.GET.get('periodo'))
    frequencia = frequencia_no_periodo(aluno, periodo)
    
    presenca_aulas = presenca_em_aulas_no_periodo(aluno, periodo)

    # 6. Evolução da carga por exercício
    cargas = evolucao_de_carga(aluno)


    avaliacoes = sorted(
        aluno.avaliacoes_fisicas.select_related('corrige').prefetch_related('testes', 'correcoes'),
        key=chave_cronologica,
    )
    por_id = {a.pk: a for a in avaliacoes}
    vigentes = [a for a in avaliacoes if a.vigente]


    parametro_a, parametro_b = request.GET.get('a'), request.GET.get('b')
    escolhida_a = escolhida_b = None
    if parametro_a is None and parametro_b is None:
        if len(vigentes) >= 2:
            escolhida_a, escolhida_b = vigentes[-2], vigentes[-1]
    else:
        escolhida_a = por_id.get(_inteiro(parametro_a))
        escolhida_b = por_id.get(_inteiro(parametro_b))
        if escolhida_a is None or escolhida_b is None:
            messages.error(request, 'Escolha duas avaliações da lista.')
            escolhida_a = escolhida_b = None
        elif escolhida_a.pk == escolhida_b.pk:
            messages.error(request, 'Escolha duas avaliações diferentes para comparar.')
            escolhida_a = escolhida_b = None

    anterior = posterior = None
    linhas = []
    if escolhida_a and escolhida_b:
        anterior, posterior, linhas = comparar_avaliacoes(escolhida_a, escolhida_b)

    return render(request, 'retencao/numeros_da_academia.html', {
        'aluno': aluno,
        'periodos': [(chave, rotulo) for chave, (rotulo, _) in PERIODOS.items()],
        'periodo': periodo,
        'frequencia': frequencia,
        'avaliacoes': avaliacoes,
        'escolhida_a': escolhida_a,
        'escolhida_b': escolhida_b,
        'anterior': anterior,
        'posterior': posterior,
        'linhas': linhas,
        'presenca_aulas': presenca_aulas,
        'cargas': cargas,
    })

def _celula(valor):
    """Texto seguro para CSV. Nome começando com = + - @ viraria fórmula ao abrir no
    Excel (injeção de fórmula); o apóstrofo força texto."""
    texto = '' if valor is None else str(valor)
    return "'" + texto if texto[:1] in ('=', '+', '-', '@', '\t', '\r') else texto

def _decimal(valor):      
    return '' if valor is None else str(valor).replace('.', ',')

def _data_br(valor):
    return valor.strftime('%d/%m/%Y') if valor else ''

def _sim_nao(valor):
    return 'Sim' if valor else 'Não'


def _linhas_risco(dados):
    for l in dados['risco']['linhas']:
        yield [
            l['aluno'].nome, l['telefone'], l['email'], l['plano'], l['situacao'],
            l['acessos_anterior'], l['acessos_atual'],
            _decimal(l['media_anterior']), _decimal(l['media_atual']), l['queda_texto'],
            _data_br(l['ultimo_acesso']),
            '' if l['dias_sem_vir'] is None else l['dias_sem_vir'],
            _sim_nao(l['sumiu']),
        ]

def _linhas_renovacao(dados):
    for l in dados['renovacao']['linhas']:
        yield [
            l['aluno'].nome, l['telefone'], l['plano'],
            l['ciclo'], _data_br(l['fim_ciclo']), l['resultado_texto'],
        ]

def _linhas_ocupacao(dados):
    for l in dados['ocupacao']['linhas']:
        yield [
            l['rotulo'], l['sala'], l['professor'], l['capacidade'],
            l['aulas'], l['presencas'],
            _decimal(l['media_presentes']),
            _sim_nao(l['ativa']),
            _decimal(l['ocupacao']),         
        ]
def _linhas_frequencia(dados):
    for l in dados['frequencia']['linhas']:
        yield [
            l['aluno'].nome, l['plano'],
            l['dias_de_matricula'], l['dias_com_acesso'],
            _decimal(l['media_semanal']),
            _data_br(l['ultimo_acesso']),
            _sim_nao(l['entra_na_media']),
        ]
EXPORTACOES = {
    'risco': ('risco-de-evasao',
              ['Aluno', 'Telefone', 'E-mail', 'Plano', 'Situação da matrícula',
               'Dias com acesso (período anterior)', 'Dias com acesso (período)',
               'Média/semana (anterior)', 'Média/semana (período)', 'Queda',
               'Último acesso', 'Dias sem vir', 'Não veio nenhuma vez?'],
              _linhas_risco),
                
                'ocupacao': ('ocupacao-das-turmas',
                 ['Turma', 'Sala', 'Professor', 'Capacidade', 'Aulas com chamada',
                  'Presenças', 'Média de presentes', 'Turma ativa', 'Ocupação (%)'],
                 _linhas_ocupacao),
    
    'renovacao': ('taxa-de-renovacao',
                  ['Aluno', 'Telefone', 'Plano', 'Ciclo', 'Fim do ciclo', 'Resultado'],
                  _linhas_renovacao),
    
    'frequencia': ('frequencia-media',
                   ['Aluno', 'Plano', 'Dias de matrícula', 'Dias com acesso',
                    'Média/semana', 'Último acesso', 'Entra na média'],
                   _linhas_frequencia),
}


def _exportar(nome, periodo, dados):
    arquivo, cabecalho, gerar = EXPORTACOES[nome]
    resposta = HttpResponse(content_type='text/csv; charset=utf-8')
    resposta['Content-Disposition'] = (
        f'attachment; filename="{arquivo}_{periodo.inicio:%Y-%m-%d}_a_{periodo.fim:%Y-%m-%d}.csv"'
    )
    resposta.write('\ufeff')                          
    escritor = csv.writer(resposta, delimiter=';')    
    escritor.writerow(cabecalho)
    for linha in gerar(dados):
        escritor.writerow([_celula(c) if isinstance(c, str) else c for c in linha])
    return resposta


@perfil_requerido('financeiro', 'admin')
def relatorios_retencao(request):
    periodo, erro = relatorios.resolver_periodo(
        request.GET.get('periodo'), request.GET.get('de'), request.GET.get('ate'),
    )
    exportar = request.GET.get('exportar')
    if exportar is not None and exportar not in EXPORTACOES:
        raise Http404('Relatório desconhecido.')
    if erro:
        messages.error(request, erro)
        exportar = None  

    dados = relatorios.montar_relatorios(periodo)
    if exportar:
        return _exportar(exportar, periodo, dados)

    parametros = periodo.parametros()
    return render(request, 'retencao/relatorios.html', {
        'periodo': periodo,
        'atalhos': [(chave, rotulo) for chave, (rotulo, _) in PERIODOS.items()],
        'personalizado': periodo.chave == relatorios.PERIODO_PERSONALIZADO,
        'dados': dados,
        'frequencia': dados['frequencia'], 'ocupacao': dados['ocupacao'],
        'risco': dados['risco'], 'renovacao': dados['renovacao'],
        'exportacoes': {nome: '?' + urlencode({**parametros, 'exportar': nome}) for nome in EXPORTACOES},
        'limite_dias': relatorios.LIMITE_PERIODO_PERSONALIZADO_DIAS,
    })


