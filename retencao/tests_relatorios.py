"""Testes dos relatórios de retenção do financeiro (T23)."""
import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from agendamentos.models import Agendamento
from alunos.models import Aluno
from financeiro.models import Cancelamento, Matricula, Plano, Renovacao, Trancamento
from financeiro.servicos import fim_vigencia
from recepcao.models import Frequencia as Entrada
from turmas.models import Frequencia as PresencaAula, Modalidade, Turma

from . import relatorios
from .relatorios import (
    Periodo, alunos_em_risco, formatar_telefone, frequencia_media, ocupacao_turmas,
    resolver_periodo, taxa_renovacao,
)

_seq = count(1)


class BaseT23(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.periodo = resolver_periodo('30', hoje=self.hoje)[0]
        self.plano = Plano.objects.create(
            nome='Mensal', modalidades_incluidas='Musculação', periodicidade='mensal',
            valor=Decimal('100.00'),
        )

    # ---- fabricas ----
    def usuario(self, tipo, **extra):
        n = next(_seq)
        u = User.objects.create_user(username=f'u{n}', password='senha12345', **extra)
        Perfil.objects.create(usuario=u, tipo=tipo)
        return u

    def aluno(self, nome='Ana Souza', dias_matricula=120, plano=None, ativo=True, matricular=True):
        n = next(_seq)
        u = User.objects.create_user(username=f'a{n}', password='senha12345')
        perfil = Perfil.objects.create(usuario=u, tipo=Perfil.ALUNO)
        aluno = Aluno.objects.create(
            perfil=perfil, nome=nome, cpf=f'{n:011d}', data_nascimento=date(2000, 1, 1),
            endereco='Rua A, 1', telefone=f'81{900000000 + n}', email=f'a{n}@exemplo.com',
            contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
            ativo=ativo,
        )
        if matricular:
            aluno.matricula = self.matricular(aluno, dias_matricula, plano)
        return aluno

    def matricular(self, aluno, dias_atras=120, plano=None):
        return Matricula.objects.create(
            aluno=aluno, plano=plano or self.plano,
            data_inicio=self.hoje - timedelta(days=dias_atras), forma_pagamento='pix',
        )

    def vir(self, aluno, *dias_atras, liberado=True):
        """Uma entrada ao meio-dia de cada dia indicado (data_hora é auto_now_add)."""
        for d in dias_atras:
            e = Entrada.objects.create(aluno=aluno, liberado=liberado)
            quando = timezone.make_aware(
                datetime.combine(self.hoje - timedelta(days=d), time(12, 0))
            )
            Entrada.objects.filter(pk=e.pk).update(data_hora=quando)

    def vinha_e_sumiu(self, aluno):
        """8 dias no período anterior ([H-59, H-30]) e nenhum no atual."""
        self.vir(aluno, *range(31, 59, 4)[:7], 58)

    def turma(self, capacidade=10, modalidade='Spinning', ativo=True):
        prof = self.usuario(Perfil.PROFESSOR, first_name='Paula', last_name='Lima')
        mod, _ = Modalidade.objects.get_or_create(nome=modalidade)
        return Turma.objects.create(
            modalidade=mod, dia_semana='segunda', horario=time(18, 0), professor=prof,
            sala='Sala 1', capacidade_maxima=capacidade, ativo=ativo,
        )

    def chamada(self, turma, dias_atras, presentes, faltas=0):
        """Registra a chamada de uma aula com `presentes` presentes e `faltas` faltas."""
        data = self.hoje - timedelta(days=dias_atras)
        for i in range(presentes + faltas):
            u = self.aluno(nome=f'Aluno {next(_seq)}', matricular=False).perfil.usuario
            PresencaAula.objects.create(turma=turma, aluno=u, data=data, presente=i < presentes)


# ======================================================================
class PeriodoTests(BaseT23):
    def test_atalho_termina_hoje_e_inclui_hoje(self):
        p, erro = resolver_periodo('7', hoje=self.hoje)
        self.assertIsNone(erro)
        self.assertEqual(p.fim, self.hoje)
        self.assertEqual(p.inicio, self.hoje - timedelta(days=6))
        self.assertEqual(p.dias, 7)

    def test_padrao_quando_nao_informa_ou_valor_desconhecido(self):
        for valor in (None, '', 'xyz'):
            p, erro = resolver_periodo(valor, hoje=self.hoje)
            self.assertEqual((p.chave, p.dias, erro), ('30', 30, None))

    def test_periodo_anterior_tem_o_mesmo_tamanho_e_cola_no_atual(self):
        p, _ = resolver_periodo('30', hoje=self.hoje)
        a = p.anterior()
        self.assertEqual(a.dias, p.dias)
        self.assertEqual(a.fim, p.inicio - timedelta(days=1))

    def test_personalizado_valido(self):
        p, erro = resolver_periodo('personalizado', '2026-01-01', '2026-01-31', hoje=date(2026, 6, 1))
        self.assertIsNone(erro)
        self.assertEqual((p.inicio, p.fim, p.dias), (date(2026, 1, 1), date(2026, 1, 31), 31))
        self.assertEqual(p.parametros(), {'periodo': 'personalizado', 'de': '2026-01-01', 'ate': '2026-01-31'})

    def test_personalizado_nao_passa_de_hoje(self):
        p, erro = resolver_periodo('personalizado', '2026-05-01', '2030-01-01', hoje=date(2026, 6, 1))
        self.assertIsNone(erro)
        self.assertEqual(p.fim, date(2026, 6, 1))

    def test_personalizado_invalido_cai_no_padrao_com_motivo(self):
        casos = [
            ('personalizado', None, None),             # sem datas
            ('personalizado', '2026-01-01', None),     # falta uma
            ('personalizado', 'lixo', '2026-01-31'),   # data inválida
            ('personalizado', '2026-02-01', '2026-01-01'),   # invertido
            ('personalizado', '2030-01-01', '2030-02-01'),   # início no futuro
            ('personalizado', '2020-01-01', '2026-05-01'),   # longo demais
        ]
        for chave, de, ate in casos:
            p, erro = resolver_periodo(chave, de, ate, hoje=date(2026, 6, 1))
            self.assertEqual(p.chave, '30', (de, ate))
            self.assertTrue(erro, (de, ate))

    def test_formatar_telefone(self):
        self.assertEqual(formatar_telefone('81999998888'), '(81) 99999-8888')
        self.assertEqual(formatar_telefone('8133334444'), '(81) 3333-4444')
        self.assertEqual(formatar_telefone(''), '')


# ======================================================================
class FrequenciaMediaTests(BaseT23):
    def test_media_por_semana_conta_dias_e_nao_passagens(self):
        ana = self.aluno('Ana')
        self.vir(ana, 0, 0, 0, 1, 2, 3)     # 4 dias distintos (3 passagens hoje = 1 dia)
        r = frequencia_media(self.periodo)
        linha = r['linhas'][0]
        self.assertEqual(linha['dias_com_acesso'], 4)
        # 4 dias em 30 dias de matrícula no período = 4 * 7 / 30 = 0,9
        self.assertEqual(linha['media_semanal'], Decimal('0.9'))

    def test_acesso_barrado_nao_conta(self):
        ana = self.aluno('Ana')
        self.vir(ana, 1, 2, 3, liberado=False)
        self.assertEqual(frequencia_media(self.periodo)['linhas'][0]['dias_com_acesso'], 0)

    def test_quem_nao_veio_entra_na_media_com_zero(self):
        ana, bia = self.aluno('Ana'), self.aluno('Bia')
        self.vir(ana, *range(0, 30, 3))      # 10 dias -> 2,3/semana
        r = frequencia_media(self.periodo)
        self.assertEqual(r['alunos_na_media'], 2)
        self.assertEqual(r['sem_nenhum_acesso'], 1)
        # (2,3 + 0) / 2 = 1,2
        self.assertEqual(r['media_geral'], Decimal('1.2'))

    def test_acesso_fora_do_periodo_nao_conta(self):
        ana = self.aluno('Ana')
        self.vir(ana, 40, 50)
        self.assertEqual(frequencia_media(self.periodo)['linhas'][0]['dias_com_acesso'], 0)

    def test_recem_matriculado_aparece_mas_fica_fora_da_media(self):
        veterana, nova = self.aluno('Veterana'), self.aluno('Nova', dias_matricula=3)
        self.vir(veterana, *range(0, 30, 3))
        r = frequencia_media(self.periodo)
        self.assertEqual(len(r['linhas']), 2)
        self.assertEqual(r['alunos_na_media'], 1)
        self.assertEqual(r['alunos_fora_da_media'], 1)
        self.assertEqual(r['media_geral'], Decimal('2.3'))

    def test_semanas_de_matricula_so_contam_o_tempo_em_vigor(self):
        ana = self.aluno('Ana', dias_matricula=13)         # 14 dias no período (H-13 a H)
        self.vir(ana, 0, 2, 4, 6)                          # 4 dias -> 4*7/14 = 2,0
        self.assertEqual(frequencia_media(self.periodo)['linhas'][0]['media_semanal'], Decimal('2.0'))

    def test_cancelada_antes_do_periodo_ou_desativada_nao_entra(self):
        antiga = self.aluno('Antiga')
        Cancelamento.objects.create(matricula=antiga.matricula, data=self.hoje - timedelta(days=60))
        self.aluno('Inativa', ativo=False)
        self.aluno('Ativa')
        nomes = [l['aluno'].nome for l in frequencia_media(self.periodo)['linhas']]
        self.assertEqual(nomes, ['Ativa'])

    def test_trancamento_reduz_as_semanas_em_vigor(self):
        ana = self.aluno('Ana')
        Trancamento.objects.create(
            matricula=ana.matricula, data_inicio=self.hoje - timedelta(days=19),
            data_fim=self.hoje - timedelta(days=10),   # 10 dias trancada
        )
        self.assertEqual(frequencia_media(self.periodo)['linhas'][0]['dias_de_matricula'], 20)

    def test_sem_alunos_nao_quebra_nem_inventa_zero(self):
        r = frequencia_media(self.periodo)
        self.assertEqual(r['linhas'], [])
        self.assertIsNone(r['media_geral'])

    def test_aluno_com_duas_matriculas_sobrepostas_nao_conta_dobrado(self):
        ana = self.aluno('Ana')
        self.matricular(ana, 100)
        self.assertEqual(len(frequencia_media(self.periodo)['linhas']), 1)


# ======================================================================
class OcupacaoTests(BaseT23):
    def test_ocupacao_e_presenca_sobre_capacidade_vezes_aulas(self):
        t = self.turma(capacidade=10)
        self.chamada(t, 7, presentes=6, faltas=2)
        self.chamada(t, 14, presentes=4)
        r = ocupacao_turmas(self.periodo)
        linha = r['linhas'][0]
        self.assertEqual((linha['aulas'], linha['presencas']), (2, 10))
        self.assertEqual(linha['ocupacao'], Decimal('50.0'))       # 10 / (10 × 2)
        self.assertEqual(linha['media_presentes'], Decimal('5.0'))
        self.assertEqual(r['ocupacao_geral'], Decimal('50.0'))

    def test_reserva_nao_conta_so_a_presenca(self):
        t = self.turma(capacidade=10)
        for i in range(10):    # turma 100% RESERVADA
            a = self.aluno(f'Reservada {i}', matricular=False)
            Agendamento.objects.create(turma=t, aluno=a, status='reservado')
        self.chamada(t, 7, presentes=3, faltas=7)     # mas só 3 foram
        self.assertEqual(ocupacao_turmas(self.periodo)['linhas'][0]['ocupacao'], Decimal('30.0'))

    def test_chamada_so_com_faltas_e_aula_com_zero_presentes(self):
        t = self.turma(capacidade=10)
        self.chamada(t, 7, presentes=0, faltas=4)
        linha = ocupacao_turmas(self.periodo)['linhas'][0]
        self.assertEqual((linha['aulas'], linha['ocupacao']), (1, Decimal('0.0')))

    def test_turma_sem_chamada_fica_em_branco_e_nao_puxa_a_geral(self):
        com, sem = self.turma(10, 'Spinning'), self.turma(10, 'Yoga')
        self.chamada(com, 7, presentes=8)
        r = ocupacao_turmas(self.periodo)
        por_nome = {l['rotulo'].split(' —')[0]: l for l in r['linhas']}
        self.assertIsNone(por_nome['Yoga']['ocupacao'])
        self.assertEqual(por_nome['Spinning']['ocupacao'], Decimal('80.0'))
        self.assertEqual(r['ocupacao_geral'], Decimal('80.0'))
        self.assertEqual((r['turmas_com_chamada'], r['turmas_sem_chamada']), (1, 1))

    def test_chamada_fora_do_periodo_nao_conta(self):
        t = self.turma(10)
        self.chamada(t, 45, presentes=10)
        self.assertIsNone(ocupacao_turmas(self.periodo)['linhas'][0]['ocupacao'])

    def test_turma_desativada_com_chamada_no_periodo_aparece_sem_chamada_nao(self):
        com_chamada = self.turma(10, 'Dança', ativo=False)
        self.turma(10, 'Pilates', ativo=False)
        self.chamada(com_chamada, 7, presentes=5)
        nomes = [l['rotulo'].split(' —')[0] for l in ocupacao_turmas(self.periodo)['linhas']]
        self.assertEqual(nomes, ['Dança'])

    def test_sem_nenhuma_turma_nao_quebra(self):
        r = ocupacao_turmas(self.periodo)
        self.assertEqual(r['linhas'], [])
        self.assertIsNone(r['ocupacao_geral'])


# ======================================================================
class RiscoDeEvasaoTests(BaseT23):
    def test_quem_vinha_e_sumiu_aparece_com_o_contato(self):
        ana = self.aluno('Ana')
        self.vinha_e_sumiu(ana)
        r = alunos_em_risco(self.periodo, hoje=self.hoje)
        self.assertEqual(r['total'], 1)
        linha = r['linhas'][0]
        self.assertTrue(linha['sumiu'])
        self.assertEqual(linha['telefone'], formatar_telefone(ana.telefone))
        self.assertEqual(linha['email'], ana.email)
        self.assertEqual(linha['acessos_atual'], 0)
        self.assertEqual(linha['dias_sem_vir'], 31)    # último acesso: 31 dias atrás
        self.assertEqual(linha['queda_texto'], '100%')

    def test_quem_segue_vindo_nao_aparece(self):
        ana = self.aluno('Ana')
        self.vir(ana, *range(0, 60, 4))
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_queda_exatamente_no_limite_entra_e_logo_abaixo_nao(self):
        # anterior: 8 dias em 30 -> 1,87/sem; limite = 50% -> até 0,93/sem no período
        no_limite, abaixo = self.aluno('No limite'), self.aluno('Abaixo do limite')
        for a in (no_limite, abaixo):
            self.vir(a, *range(31, 59, 4)[:7], 58)
        self.vir(no_limite, 1, 5, 9, 13)           # 4 dias: 0,93/sem  (50% de queda: entra)
        self.vir(abaixo, 1, 5, 9, 13, 17)          # 5 dias: 1,17/sem  (só 37%: não entra)
        nomes = [l['aluno'].nome for l in alunos_em_risco(self.periodo, hoje=self.hoje)['linhas']]
        self.assertEqual(nomes, ['No limite'])

    def test_queda_parcial_nao_e_sumico(self):
        ana = self.aluno('Ana')
        self.vir(ana, *range(31, 59, 4)[:7], 58)   # 8 dias antes
        self.vir(ana, 2, 12)                       # 2 dias agora
        linha = alunos_em_risco(self.periodo, hoje=self.hoje)['linhas'][0]
        self.assertFalse(linha['sumiu'])
        self.assertEqual(linha['acessos_atual'], 2)

    def test_quem_nunca_vinha_nao_esta_em_risco(self):
        self.aluno('Nunca veio')
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_quem_vinha_pouco_nao_esta_em_risco(self):
        ana = self.aluno('Ana')
        self.vir(ana, 33, 45, 55)     # 3 dias em 30 = 0,7/sem: abaixo de "pelo menos 1 por semana"
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_matricula_recente_nao_tem_base_para_dizer_que_vinha(self):
        nova = self.aluno('Nova', dias_matricula=34)       # só 4 dias no período anterior
        self.vir(nova, 31, 32, 33, 34)
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_matricula_cancelada_nao_entra(self):
        ana = self.aluno('Ana')
        self.vinha_e_sumiu(ana)
        Cancelamento.objects.create(matricula=ana.matricula, data=self.hoje - timedelta(days=2))
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_matricula_trancada_nao_entra(self):
        ana = self.aluno('Ana')
        self.vinha_e_sumiu(ana)
        Trancamento.objects.create(
            matricula=ana.matricula, data_inicio=self.hoje - timedelta(days=25), data_fim=None,
        )
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_aluno_desativado_nao_entra(self):
        ana = self.aluno('Ana', ativo=False)
        self.vinha_e_sumiu(ana)
        self.assertEqual(alunos_em_risco(self.periodo, hoje=self.hoje)['total'], 0)

    def test_matricula_bloqueada_entra_identificada(self):
        from financeiro.models import Cobranca
        ana = self.aluno('Ana')
        self.vinha_e_sumiu(ana)
        Cobranca.objects.create(
            matricula=ana.matricula, tipo='mensalidade', valor=Decimal('100'),
            vencimento=self.hoje - timedelta(days=40), competencia='2020-01',
        )
        linha = alunos_em_risco(self.periodo, hoje=self.hoje)['linhas'][0]
        self.assertEqual(linha['situacao_codigo'], 'bloqueada')

    def test_acesso_barrado_nao_conta_como_ter_vindo(self):
        ana = self.aluno('Ana')
        self.vinha_e_sumiu(ana)
        self.vir(ana, 1, 2, 3, 4, 5, liberado=False)      # tentou, a catraca barrou
        self.assertTrue(alunos_em_risco(self.periodo, hoje=self.hoje)['linhas'][0]['sumiu'])

    def test_o_filtro_de_periodo_muda_quem_esta_em_risco(self):
        ana = self.aluno('Ana')
        self.vir(ana, 8, 10, 12)         # veio 3x na semana de H-13 a H-7 e depois parou
        sete, _ = resolver_periodo('7', hoje=self.hoje)
        trinta, _ = resolver_periodo('30', hoje=self.hoje)
        self.assertEqual(alunos_em_risco(sete, hoje=self.hoje)['total'], 1)
        self.assertEqual(alunos_em_risco(trinta, hoje=self.hoje)['total'], 0)

    def test_ordem_quem_sumiu_ha_mais_tempo_primeiro(self):
        recente, antigo, parcial = self.aluno('Recente'), self.aluno('Antigo'), self.aluno('Parcial')
        self.vir(recente, *range(31, 59, 4)[:7], 58, 29)      # último acesso há 29 dias
        self.vir(antigo, *range(40, 59, 2), 59)               # último acesso há 40 dias
        self.vir(parcial, *range(31, 59, 4)[:7], 58, 2, 12)
        nomes = [l['aluno'].nome for l in alunos_em_risco(self.periodo, hoje=self.hoje)['linhas']]
        self.assertEqual(nomes, ['Antigo', 'Recente', 'Parcial'])

    def test_regra_exposta_para_a_tela(self):
        r = alunos_em_risco(self.periodo, hoje=self.hoje)
        self.assertEqual(r['queda_minima_pct'], 50)
        self.assertEqual(r['anterior'], self.periodo.anterior())


# ======================================================================
class TaxaRenovacaoTests(BaseT23):
    def aluno_que_vence_no_periodo(self, nome, plano=None, dias=45):
        a = self.aluno(nome, dias_matricula=dias, plano=plano)
        self.assertTrue(self.periodo.inicio <= fim_vigencia(a.matricula) <= self.periodo.fim)
        return a

    def renovar(self, matricula):
        fim = fim_vigencia(matricula)
        return Renovacao.objects.create(
            matricula=matricula, ciclo=2, inicio=fim, fim=fim + timedelta(days=30),
            meses_acumulados=2,
        )

    def test_renovou_cancelou_e_ainda_sem_renovacao(self):
        renovou = self.aluno_que_vence_no_periodo('Renovou')
        self.renovar(renovou.matricula)
        cancelou = self.aluno_que_vence_no_periodo('Cancelou')
        Cancelamento.objects.create(matricula=cancelou.matricula, data=self.hoje - timedelta(days=3))
        self.aluno_que_vence_no_periodo('Pendente')

        r = taxa_renovacao(self.periodo)
        self.assertEqual((r['base'], r['renovaram'], r['cancelaram'], r['sem_renovacao']), (3, 1, 1, 1))
        self.assertEqual(r['taxa'], Decimal('33.3'))
        resultados = {l['aluno'].nome: l['resultado'] for l in r['linhas']}
        self.assertEqual(
            resultados, {'Renovou': 'renovou', 'Cancelou': 'cancelou', 'Pendente': 'sem_renovacao'},
        )

    def test_ciclo_que_nao_termina_no_periodo_nao_entra(self):
        self.aluno('Longe do fim', dias_matricula=5)      # mensal: vence daqui a ~25 dias
        r = taxa_renovacao(self.periodo)
        self.assertEqual((r['base'], r['taxa']), (0, None))

    def test_renovada_no_ciclo_seguinte_so_conta_o_ciclo_que_terminou(self):
        a = self.aluno_que_vence_no_periodo('Ana')
        self.renovar(a.matricula)
        # o ciclo 2 termina no futuro: não pode virar "sem renovação" agora
        self.assertEqual(taxa_renovacao(self.periodo)['base'], 1)

    def test_cancelada_antes_do_periodo_nao_entra(self):
        trimestral = Plano.objects.create(
            nome='Tri', modalidades_incluidas='X', periodicidade='trimestral', valor=Decimal('90'),
        )
        a = self.aluno('Ana', dias_matricula=100, plano=trimestral)    # termina ~ H-9
        Cancelamento.objects.create(matricula=a.matricula, data=self.hoje - timedelta(days=60))
        self.assertEqual(taxa_renovacao(self.periodo)['base'], 0)

    def test_periodo_sem_vencimentos_nao_mostra_zero_enganoso(self):
        self.assertIsNone(taxa_renovacao(self.periodo)['taxa'])

    def test_historico_de_ciclos_passados_aparece_no_periodo_certo(self):
        a = self.aluno('Ana', dias_matricula=75)        # mensal: ciclo 1 terminou há ~45 dias
        self.renovar(a.matricula)                       # renovou; ciclo 2 ainda não terminou
        periodo_passado = Periodo(
            'personalizado', 'x', self.hoje - timedelta(days=60), self.hoje - timedelta(days=30),
        )
        r = taxa_renovacao(periodo_passado)
        self.assertEqual((r['base'], r['renovaram'], r['taxa']), (1, 1, Decimal('100.0')))


# ======================================================================
class TelaEExportacaoTests(BaseT23):
    def setUp(self):
        super().setUp()
        self.financeiro = self.usuario(Perfil.FINANCEIRO)
        self.url = reverse('relatorios_retencao')

    def entrar(self, usuario=None):
        self.client.force_login(usuario or self.financeiro)

    def csv_de(self, nome, **parametros):
        r = self.client.get(self.url, {'exportar': nome, **parametros})
        self.assertEqual(r.status_code, 200)
        texto = r.content.decode('utf-8-sig')
        return r, list(csv.reader(io.StringIO(texto), delimiter=';'))

    # ---- acesso ----
    def test_anonimo_vai_para_o_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('entrar', r.url)

    def test_aluna_professor_e_recepcao_nao_acessam(self):
        for tipo in (Perfil.ALUNO, Perfil.PROFESSOR, Perfil.RECEPCAO):
            self.entrar(self.usuario(tipo))
            self.assertEqual(self.client.get(self.url).status_code, 302, tipo)
            self.assertEqual(self.client.get(self.url, {'exportar': 'risco'}).status_code, 302, tipo)

    def test_financeiro_e_admin_acessam(self):
        self.entrar()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.entrar(self.usuario(Perfil.ADMIN))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    # ---- tela ----
    def test_tela_mostra_os_quatro_relatorios_e_a_regra(self):
        self.entrar()
        html = self.client.get(self.url).content.decode()
        for trecho in (
            'Frequência média dos alunos', 'Ocupação das turmas', 'Alunos em risco de evasão',
            'Taxa de renovação', 'Como a lista é montada', 'caiu 50% ou mais',
            'Exportar CSV',
        ):
            self.assertIn(trecho, html)

    def test_lista_de_risco_mostra_o_telefone_do_aluno_para_a_recepcao_ligar(self):
        ana = self.aluno('Ana Sumida')
        self.vinha_e_sumiu(ana)
        self.entrar()
        html = self.client.get(self.url).content.decode()
        self.assertIn('Ana Sumida', html)
        self.assertIn(formatar_telefone(ana.telefone), html)
        self.assertIn(f'tel:{ana.telefone}', html)

    def test_o_mesmo_filtro_vale_para_os_quatro(self):
        self.entrar()
        r = self.client.get(self.url, {'periodo': '7'})
        self.assertEqual(r.context['periodo'].dias, 7)
        # todos os relatórios foram calculados sobre o período escolhido
        self.assertEqual(r.context['risco']['anterior'].dias, 7)
        html = r.content.decode()
        self.assertEqual(html.count('value="personalizado"'), 1)    # só o form do intervalo
        for chave in ('periodo=7', 'periodo=30', 'periodo=90', 'periodo=365'):
            self.assertIn(chave, html)

    def test_periodo_invalido_avisa_e_usa_o_padrao(self):
        self.entrar()
        r = self.client.get(self.url, {'periodo': 'personalizado', 'de': '2026-02-01', 'ate': '2026-01-01'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['periodo'].chave, '30')
        self.assertContains(r, 'não pode ser depois')

    # ---- exportação ----
    def test_exporta_o_risco_com_telefone_no_arquivo(self):
        ana = self.aluno('Ana Sumida')
        self.vinha_e_sumiu(ana)
        self.entrar()
        r, linhas = self.csv_de('risco')
        self.assertTrue(r['Content-Type'].startswith('text/csv'))
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('risco-de-evasao', r['Content-Disposition'])
        self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))      # BOM para o Excel
        self.assertEqual(linhas[0][:3], ['Aluno', 'Telefone', 'E-mail'])
        self.assertEqual(linhas[1][0], 'Ana Sumida')
        self.assertEqual(linhas[1][1], formatar_telefone(ana.telefone))
        self.assertEqual(linhas[1][-1], 'Sim')

    def test_exporta_cada_listagem(self):
        self.entrar()
        ana = self.aluno('Ana')
        self.vir(ana, 1, 2)
        t = self.turma(10)
        self.chamada(t, 3, presentes=5)
        for nome, primeira_coluna in (
            ('frequencia', 'Aluno'), ('ocupacao', 'Turma'), ('risco', 'Aluno'), ('renovacao', 'Aluno'),
        ):
            r, linhas = self.csv_de(nome)
            self.assertEqual(linhas[0][0], primeira_coluna, nome)
        _, linhas = self.csv_de('frequencia')
        self.assertEqual(linhas[1][0], 'Ana')
        self.assertEqual(linhas[1][3], '2')
        _, linhas = self.csv_de('ocupacao')
        self.assertEqual(linhas[1][-1], '50,0')                      # vírgula decimal (Excel BR)

    def test_exportacao_respeita_o_periodo_escolhido_e_o_nome_do_arquivo(self):
        ana = self.aluno('Ana')
        self.vir(ana, 1, 2, 3)
        self.vir(ana, 20)
        self.entrar()
        _, sete = self.csv_de('frequencia', periodo='7')
        _, trinta = self.csv_de('frequencia', periodo='30')
        self.assertEqual(sete[1][3], '3')
        self.assertEqual(trinta[1][3], '4')
        r = self.client.get(self.url, {'exportar': 'frequencia', 'periodo': '7'})
        self.assertIn(f'{self.hoje - timedelta(days=6):%Y-%m-%d}_a_{self.hoje:%Y-%m-%d}', r['Content-Disposition'])

    def test_exportacao_com_periodo_invalido_nao_entrega_arquivo_de_outro_periodo(self):
        self.entrar()
        r = self.client.get(self.url, {
            'exportar': 'risco', 'periodo': 'personalizado', 'de': 'lixo', 'ate': 'lixo',
        })
        self.assertTrue(r['Content-Type'].startswith('text/html'))
        self.assertNotIn('attachment', r.get('Content-Disposition', ''))

    def test_exportacao_desconhecida_da_404(self):
        self.entrar()
        self.assertEqual(self.client.get(self.url, {'exportar': 'tudo'}).status_code, 404)

    def test_nome_que_parece_formula_nao_vira_formula_no_excel(self):
        ana = self.aluno('=HYPERLINK("http://x")')
        self.vir(ana, 1)
        self.entrar()
        _, linhas = self.csv_de('frequencia')
        self.assertTrue(linhas[1][0].startswith("'="))

    def test_painel_financeiro_tem_o_link_para_os_relatorios(self):
        self.entrar()
        self.assertContains(self.client.get(reverse('painel_financeiro')), self.url)
