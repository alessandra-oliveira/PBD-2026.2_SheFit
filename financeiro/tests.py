from dateutil.relativedelta import relativedelta
from decimal import Decimal
from datetime import date, timedelta
from itertools import count
from importlib import import_module
import threading
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.forms import MatriculaForm as MatriculaFormDoApp
from alunos.models import Aluno, Anamnese
from .forms import MatriculaForm
from .models import (
    RegraFinanceira, HistoricoRegraFinanceira, Plano, Matricula, Cobranca,
    Trancamento, Cancelamento, SituacaoMatricula, Pagamento, Estorno, Renovacao,
)
from .servicos import (
    realizar_matricula, gerar_cobrancas, calcular_situacao, avaliar_situacao_financeira_aluno,
    saldo_cobranca, registrar_pagamento, registrar_estorno, total_estornado,
)


def criar_usuario(username, tipo):
    usuario = User.objects.create_user(username=username, password='senha12345')
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


_sequencia = count(1)


def criar_anamnese(aluno, autorizada=True):
    # Se o Anamnese tiver outros campos obrigatórios, acrescente-os aqui.
    return Anamnese.objects.create(
        aluno=aluno, autorizacao_atividade_fisica=autorizada,
    )


def criar_aluno_valido(com_anamnese=True, autorizada=True):
    n = next(_sequencia)
    usuario = User.objects.create_user(username=f'aluna{n}', password='senha12345')
    perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.ALUNO)
    aluno = Aluno.objects.create(
        perfil=perfil, nome=f'Aluna {n}', cpf=f'{n:011d}',
        data_nascimento=date(2000, 1, 1), endereco='Rua A, 1',
        telefone=f'8199{n:07d}', email=f'aluna{n}@exemplo.com',
        contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
    )
    if com_anamnese:
        criar_anamnese(aluno, autorizada=autorizada)
    return aluno


DADOS_VALIDOS = {
    'dias_tolerancia': '5',
    'juros_diario': '0.050',
    'multa_atraso': '3.00',
    'dias_bloqueio': '20',
    'limite_dias_trancamento_ano': '90',
}


class RegrasFinanceirasTests(TestCase):
    def setUp(self):
        self.url = reverse('regras_financeiras')
        self.financeiro = criar_usuario('fin', Perfil.FINANCEIRO)

    def test_anonimo_vai_para_login(self):
        resp = self.client.get(self.url)
        self.assertRedirects(resp, f"{reverse('entrar')}?next={self.url}")

    def test_outros_perfis_nao_acessam(self):
        for tipo in (Perfil.RECEPCAO, Perfil.PROFESSOR, Perfil.ALUNO):
            criar_usuario(f'u_{tipo}', tipo)
            self.client.login(username=f'u_{tipo}', password='senha12345')
            resp = self.client.get(self.url)
            self.assertRedirects(resp, reverse('painel'), fetch_redirect_response=False)
            resp = self.client.post(self.url, DADOS_VALIDOS)
            self.assertRedirects(resp, reverse('painel'), fetch_redirect_response=False)
            self.client.logout()
        self.assertEqual(HistoricoRegraFinanceira.objects.count(), 0)

    def test_financeiro_ve_a_tela(self):
        self.client.login(username='fin', password='senha12345')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_obter_cria_regras_padrao_uma_unica_vez(self):
        a = RegraFinanceira.obter()
        b = RegraFinanceira.obter()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(RegraFinanceira.objects.count(), 1)

    def test_alteracao_salva_e_registra_quem_e_quando(self):
        self.client.login(username='fin', password='senha12345')
        resp = self.client.post(self.url, DADOS_VALIDOS)
        self.assertRedirects(resp, self.url)

        regras = RegraFinanceira.obter()
        self.assertEqual(regras.dias_tolerancia, 5)
        self.assertEqual(regras.juros_diario, Decimal('0.050'))
        self.assertEqual(regras.multa_atraso, Decimal('3.00'))
        self.assertEqual(regras.dias_bloqueio, 20)
        self.assertEqual(regras.atualizado_por, self.financeiro)

        historico = HistoricoRegraFinanceira.objects.all()
        self.assertEqual(historico.count(), 4)
        item = historico.get(campo='dias_tolerancia')
        self.assertEqual((item.valor_anterior, item.valor_novo), ('3', '5'))
        self.assertEqual(item.alterado_por, self.financeiro)
        self.assertEqual(item.alterado_por_nome, 'fin')
        self.assertIsNotNone(item.alterado_em)

    def test_registra_so_o_campo_que_mudou(self):
        self.client.login(username='fin', password='senha12345')
        dados = {
            'dias_tolerancia': '3',
            'juros_diario': '0.033',
            'multa_atraso': '2.5',
            'dias_bloqueio': '15',
            'limite_dias_trancamento_ano': '90',
        }
        self.client.post(self.url, dados)
        historico = HistoricoRegraFinanceira.objects.all()
        self.assertEqual(historico.count(), 1)
        self.assertEqual(historico[0].campo, 'multa_atraso')
        self.assertEqual((historico[0].valor_anterior, historico[0].valor_novo), ('2.00', '2.50'))

    def test_salvar_sem_mudar_nada_nao_gera_historico(self):
        self.client.login(username='fin', password='senha12345')
        padrao = RegraFinanceira.PADRAO
        self.client.post(self.url, {k: str(v) for k, v in padrao.items()})
        self.assertEqual(HistoricoRegraFinanceira.objects.count(), 0)

    def test_nenhum_campo_pode_ficar_em_branco(self):
        self.client.login(username='fin', password='senha12345')
        for campo in DADOS_VALIDOS:
            dados = dict(DADOS_VALIDOS, **{campo: ''})
            resp = self.client.post(self.url, dados)
            self.assertEqual(resp.status_code, 200, campo)
            self.assertIn(campo, resp.context['form'].errors)
        self.assertEqual(HistoricoRegraFinanceira.objects.count(), 0)

    def test_valores_negativos_sao_rejeitados(self):
        self.client.login(username='fin', password='senha12345')
        for campo in DADOS_VALIDOS:
            dados = dict(DADOS_VALIDOS, **{campo: '-1'})
            resp = self.client.post(self.url, dados)
            self.assertEqual(resp.status_code, 200, campo)
            self.assertIn(campo, resp.context['form'].errors)
        self.assertEqual(HistoricoRegraFinanceira.objects.count(), 0)

    def test_bloqueio_nao_pode_ser_menor_que_a_tolerancia(self):
        self.client.login(username='fin', password='senha12345')
        dados = dict(DADOS_VALIDOS, dias_tolerancia='10', dias_bloqueio='5')
        resp = self.client.post(self.url, dados)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('dias_bloqueio', resp.context['form'].errors)
        self.assertEqual(HistoricoRegraFinanceira.objects.count(), 0)

    def test_historico_aparece_na_tela(self):
        self.client.login(username='fin', password='senha12345')
        self.client.post(self.url, DADOS_VALIDOS)
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context['historico']), 4)


class ServicosRegrasTests(TestCase):
    def test_dentro_da_tolerancia_nao_cobra_nada(self):
        from .servicos import calcular_encargos, esta_inadimplente
        self.assertEqual(calcular_encargos('100.00', 3), {'juros': Decimal('0.00'), 'multa': Decimal('0.00')})
        self.assertFalse(esta_inadimplente(3))

    def test_apos_a_tolerancia_cobra_juros_e_multa(self):
        from .servicos import calcular_encargos, esta_inadimplente
        self.assertTrue(esta_inadimplente(4))
        self.assertEqual(calcular_encargos('100.00', 10), {'juros': Decimal('0.33'), 'multa': Decimal('2.00')})

    def test_bloqueio_no_limite_de_dias(self):
        from .servicos import acesso_bloqueado
        self.assertFalse(acesso_bloqueado(14))
        self.assertTrue(acesso_bloqueado(15))

    def test_mudar_regra_vale_para_o_calculo_novo_e_nao_para_o_resultado_ja_gravado(self):
        from .servicos import calcular_encargos
        antigo = calcular_encargos('100.00', 10)  # o que a T07 gravaria no pagamento
        regras = RegraFinanceira.obter()
        regras.multa_atraso = Decimal('5.00')
        regras.save()
        self.assertEqual(antigo['multa'], Decimal('2.00'))
        self.assertEqual(calcular_encargos('100.00', 10)['multa'], Decimal('5.00'))


class TarefaT06MatriculaServicosTests(TestCase):
    def setUp(self):
        self.aluno = criar_aluno_valido()
        self.plano = Plano.objects.create(
            nome="Trimestral",
            periodicidade="trimestral",
            valor=Decimal('150.00'),
            taxa_adesao=Decimal('40.00'),
            dia_vencimento=10
        )
        self.data_inicio = date(2027, 2, 1)

    def test_gera_adesao_e_uma_mensalidade_por_mes_da_periodicidade(self):
        matricula = realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')

        adesoes = matricula.cobrancas.filter(tipo='adesao')
        self.assertEqual(adesoes.count(), 1)
        self.assertEqual(adesoes[0].valor, Decimal('40.00'))

        mensalidades = matricula.cobrancas.filter(tipo='mensalidade').order_by('vencimento')
        self.assertEqual(
            [c.competencia for c in mensalidades], ['2027-02', '2027-03', '2027-04'],
        )
        self.assertEqual(
            [c.vencimento for c in mensalidades],
            [date(2027, 2, 10), date(2027, 3, 10), date(2027, 4, 10)],
        )
        self.assertTrue(all(c.valor == Decimal('150.00') for c in mensalidades))

    def test_sem_taxa_de_adesao_nao_gera_cobranca_de_adesao(self):
        self.plano.taxa_adesao = Decimal('0.00')
        self.plano.save()
        matricula = realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')
        self.assertFalse(matricula.cobrancas.filter(tipo='adesao').exists())
        self.assertEqual(matricula.cobrancas.count(), 3)

    def test_mensalidade_da_mesma_competencia_nao_duplica(self):
        """A idempotência vale por (matrícula, competência): repetir a mesma
        competência na mesma matrícula não cria outra cobrança."""
        matricula = realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')
        antes = matricula.cobrancas.count()

        existente = matricula.cobrancas.filter(tipo='mensalidade').first()
        _, criada = Cobranca.objects.get_or_create(
            matricula=matricula, competencia=existente.competencia,
            defaults={'tipo': 'mensalidade', 'valor': self.plano.valor,
                      'vencimento': existente.vencimento},
        )
        self.assertFalse(criada)
        self.assertEqual(matricula.cobrancas.count(), antes)

    def test_nova_matricula_nao_mexe_nas_cobrancas_da_anterior(self):
        primeira = realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')
        antes = primeira.cobrancas.count()
        segunda = realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')
        self.assertNotEqual(primeira.pk, segunda.pk)
        self.assertEqual(primeira.cobrancas.count(), antes)

    def test_bloqueio_aluno_sem_anamnese(self):
        aluno = criar_aluno_valido(com_anamnese=False)
        with self.assertRaises(ValidationError):
            realizar_matricula(aluno, self.plano, self.data_inicio, 'pix')
        self.assertEqual(Matricula.objects.count(), 0)  # nada foi gravado

    def test_bloqueio_aluno_sem_autorizacao_na_anamnese(self):
        aluno = criar_aluno_valido(autorizada=False)
        with self.assertRaises(ValidationError):
            realizar_matricula(aluno, self.plano, self.data_inicio, 'pix')
        self.assertEqual(Matricula.objects.count(), 0)

    def test_bloqueio_aluno_desativado_mesmo_com_anamnese_autorizada(self):
        self.aluno.ativo = False
        self.aluno.save()
        with self.assertRaises(ValidationError):
            realizar_matricula(self.aluno, self.plano, self.data_inicio, 'pix')
        self.assertEqual(Matricula.objects.count(), 0)

class TarefaT08SituacaoMatriculaTests(TestCase):
    """A situação nunca é digitada: nasce de cancelamento, trancamento e cobranças.
    Regras padrão: tolerância 3 dias, bloqueio a partir de 15 dias."""

    def setUp(self):
        RegraFinanceira.obter()  # cria as regras padrão (3 / 15)
        self.hoje = date(2027, 3, 20)
        self.plano = Plano.objects.create(
            nome='Mensal', periodicidade='mensal', valor=Decimal('100.00'), dia_vencimento=10,
        )
        self.matricula = Matricula.objects.create(
            aluno=criar_aluno_valido(), plano=self.plano,
            data_inicio=date(2027, 1, 1), forma_pagamento='pix',
        )
        self._n = count(1)

    # ---- apoio -------------------------------------------------------
    def cobranca(self, dias_de_atraso, paga=False):
        """Cria uma mensalidade que venceu há `dias_de_atraso` dias (negativo = vence no futuro)."""
        return Cobranca.objects.create(
            matricula=self.matricula, tipo='mensalidade', valor=Decimal('100.00'),
            vencimento=self.hoje - timedelta(days=dias_de_atraso),
            competencia=f'2026-{next(self._n):02d}', paga=paga,
        )

    def situacao(self, hoje=None):
        return calcular_situacao(self.matricula, hoje=hoje or self.hoje)

    # ---- ativa -------------------------------------------------------
    def test_sem_nenhuma_cobranca_esta_ativa(self):
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_cobranca_que_ainda_vai_vencer_nao_afeta(self):
        self.cobranca(-5)
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_cobranca_que_vence_hoje_ainda_nao_esta_atrasada(self):
        self.cobranca(0)
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_cobranca_vencida_mas_paga_continua_ativa(self):
        self.cobranca(40, paga=True)
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_cobranca_vencida_dentro_da_tolerancia_continua_ativa(self):
        self.cobranca(3)
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    # ---- inadimplente ------------------------------------------------
    def test_um_dia_alem_da_tolerancia_fica_inadimplente(self):
        self.cobranca(4)
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)

    def test_ate_o_dia_anterior_ao_limite_ainda_e_inadimplente(self):
        self.cobranca(14)
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)

    # ---- bloqueada ---------------------------------------------------
    def test_no_limite_de_bloqueio_fica_bloqueada(self):
        self.cobranca(15)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)

    def test_muito_alem_do_limite_continua_bloqueada(self):
        self.cobranca(90)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)

    def test_vale_a_cobranca_em_aberto_mais_antiga(self):
        self.cobranca(4)
        self.cobranca(20)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)

    def test_passar_dos_dias_leva_de_ativa_a_inadimplente_e_a_bloqueada(self):
        self.cobranca(0)  # vence hoje
        self.assertEqual(self.situacao(self.hoje), SituacaoMatricula.ATIVA)
        self.assertEqual(self.situacao(self.hoje + timedelta(days=3)), SituacaoMatricula.ATIVA)
        self.assertEqual(self.situacao(self.hoje + timedelta(days=4)), SituacaoMatricula.INADIMPLENTE)
        self.assertEqual(self.situacao(self.hoje + timedelta(days=15)), SituacaoMatricula.BLOQUEADA)

    # ---- trancada ----------------------------------------------------
    def test_trancamento_em_curso_fica_trancada(self):
        Trancamento.objects.create(
            matricula=self.matricula,
            data_inicio=self.hoje - timedelta(days=1), data_fim=self.hoje + timedelta(days=30),
        )
        self.assertEqual(self.situacao(), SituacaoMatricula.TRANCADA)

    def test_trancamento_sem_data_de_fim_esta_em_curso(self):
        Trancamento.objects.create(matricula=self.matricula, data_inicio=self.hoje, data_fim=None)
        self.assertEqual(self.situacao(), SituacaoMatricula.TRANCADA)

    def test_trancamento_que_ja_terminou_nao_conta(self):
        Trancamento.objects.create(
            matricula=self.matricula,
            data_inicio=self.hoje - timedelta(days=30), data_fim=self.hoje - timedelta(days=1),
        )
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_trancamento_que_ainda_nao_comecou_nao_conta(self):
        Trancamento.objects.create(
            matricula=self.matricula,
            data_inicio=self.hoje + timedelta(days=1), data_fim=self.hoje + timedelta(days=30),
        )
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_trancamento_vence_o_atraso(self):
        self.cobranca(60)
        Trancamento.objects.create(matricula=self.matricula, data_inicio=self.hoje, data_fim=None)
        self.assertEqual(self.situacao(), SituacaoMatricula.TRANCADA)

    def test_ao_fim_do_trancamento_volta_a_situacao_financeira(self):
        self.cobranca(60)
        Trancamento.objects.create(
            matricula=self.matricula, data_inicio=self.hoje, data_fim=self.hoje + timedelta(days=10),
        )
        self.assertEqual(self.situacao(self.hoje + timedelta(days=9)), SituacaoMatricula.TRANCADA)
        self.assertEqual(self.situacao(self.hoje + timedelta(days=10)), SituacaoMatricula.BLOQUEADA)

    def test_trancamento_nao_aceita_fim_antes_do_inicio(self):
        t = Trancamento(matricula=self.matricula, data_inicio=self.hoje,
                        data_fim=self.hoje - timedelta(days=1))
        with self.assertRaises(ValidationError):
            t.full_clean()

    # ---- cancelada ---------------------------------------------------
    def test_cancelamento_registrado_fica_cancelada(self):
        Cancelamento.objects.create(matricula=self.matricula, data=self.hoje)
        self.assertEqual(self.situacao(), SituacaoMatricula.CANCELADA)

    def test_cancelada_vence_trancamento_e_atraso(self):
        self.cobranca(90)
        Trancamento.objects.create(matricula=self.matricula, data_inicio=self.hoje, data_fim=None)
        Cancelamento.objects.create(matricula=self.matricula, data=self.hoje)
        self.assertEqual(self.situacao(), SituacaoMatricula.CANCELADA)

    # ---- pagamento devolve a ativa ----------------------------------
    def test_pagamento_devolve_inadimplente_a_ativa(self):
        c = self.cobranca(8)
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)
        c.paga = True
        c.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_pagamento_devolve_bloqueada_a_ativa(self):
        c = self.cobranca(30)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)
        c.paga = True
        c.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_so_volta_a_ativa_quando_quita_todas_as_pendencias(self):
        antiga = self.cobranca(30)
        recente = self.cobranca(8)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)
        antiga.paga = True
        antiga.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)  # sobrou a de 8 dias
        recente.paga = True
        recente.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_pagar_nao_destranca_matricula_trancada(self):
        c = self.cobranca(30)
        Trancamento.objects.create(matricula=self.matricula, data_inicio=self.hoje, data_fim=None)
        self.assertEqual(self.situacao(), SituacaoMatricula.TRANCADA)
        c.paga = True
        c.save()
        # quitar a pendência não encerra o trancamento: só ele o encerra
        self.assertEqual(self.situacao(), SituacaoMatricula.TRANCADA)

    def test_pagar_nao_reativa_matricula_cancelada(self):
        c = self.cobranca(30)
        Cancelamento.objects.create(matricula=self.matricula, data=self.hoje)
        c.paga = True
        c.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.CANCELADA)

    # ---- regras mudam, situação acompanha ---------------------------
    def test_mudar_a_tolerancia_muda_a_situacao_sem_editar_a_matricula(self):
        self.cobranca(5)
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)
        regras = RegraFinanceira.obter()
        regras.dias_tolerancia = 10
        regras.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.ATIVA)

    def test_mudar_o_limite_de_bloqueio_muda_a_situacao(self):
        self.cobranca(20)
        self.assertEqual(self.situacao(), SituacaoMatricula.BLOQUEADA)
        regras = RegraFinanceira.obter()
        regras.dias_bloqueio = 30
        regras.save()
        self.assertEqual(self.situacao(), SituacaoMatricula.INADIMPLENTE)

    # ---- ninguém edita a situação -----------------------------------
    def test_situacao_nao_pode_ser_atribuida(self):
        with self.assertRaises(AttributeError):
            self.matricula.situacao = 'ativa'

    def test_matricula_nao_guarda_a_situacao_no_banco(self):
        campos = {f.name for f in Matricula._meta.get_fields()}
        self.assertNotIn('status', campos)
        self.assertNotIn('situacao', campos)

    def test_formulario_de_matricula_nao_expoe_a_situacao(self):
        self.assertEqual(
            set(MatriculaForm().fields), {'aluno', 'plano', 'data_inicio', 'forma_pagamento'},
        )

    def test_matricula_criada_pelo_servico_tem_situacao_valida(self):
        m = realizar_matricula(criar_aluno_valido(), self.plano, date(2027, 3, 1), 'pix')
        self.assertIn(m.situacao, SituacaoMatricula.values)
        self.assertIn(m.situacao_display, SituacaoMatricula.labels)


class TarefaT08ConsumoPelaRecepcaoTests(TestCase):
    """A porta da academia (T09) tem que obedecer à situação calculada (T08).
    Aqui "hoje" é o dia real, porque o serviço da recepção usa a data de hoje."""

    def setUp(self):
        RegraFinanceira.obter()  # tolerância 3, bloqueio 15
        self.hoje = timezone.localdate()
        self.plano = Plano.objects.create(
            nome='Mensal', periodicidade='mensal', valor=Decimal('100.00'), dia_vencimento=10,
        )
        self.aluno = criar_aluno_valido()
        self.matricula = Matricula.objects.create(
            aluno=self.aluno, plano=self.plano,
            data_inicio=self.hoje - timedelta(days=90), forma_pagamento='pix',
        )
        self._n = count(1)

    def cobranca(self, dias_de_atraso, paga=False):
        return Cobranca.objects.create(
            matricula=self.matricula, tipo='mensalidade', valor=Decimal('100.00'),
            vencimento=self.hoje - timedelta(days=dias_de_atraso),
            competencia=f'2026-{next(self._n):02d}', paga=paga,
        )

    def test_aluno_sem_matricula_e_bloqueado(self):
        outro = criar_aluno_valido()
        r = avaliar_situacao_financeira_aluno(outro)
        self.assertEqual(r['status'], 'bloqueado')

    def test_matricula_ativa_e_liberada(self):
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'liberado')

    def test_inadimplente_entra_com_aviso(self):
        self.cobranca(5)
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'liberado_com_aviso')
        self.assertEqual(r['detalhes']['dias_atraso'], 5)
        self.assertEqual(r['detalhes']['dias_restantes_bloqueio'], 10)

    def test_aviso_mostra_saldo_real_depois_de_pagamento_parcial(self):
        cobranca = self.cobranca(5)
        registrar_pagamento(
            cobranca, Decimal('50.00'), 'pix', data_pagamento=self.hoje,
        )

        resultado = avaliar_situacao_financeira_aluno(self.aluno)

        self.assertEqual(resultado['detalhes']['valor_pendente'], Decimal('52.17'))

    def test_bloqueada_nao_entra(self):
        self.cobranca(20)
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'bloqueado')
        self.assertEqual(r['detalhes']['dias_atraso'], 20)

    def test_trancada_nao_entra_mesmo_sem_atraso(self):
        Trancamento.objects.create(matricula=self.matricula, data_inicio=self.hoje, data_fim=None)
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'bloqueado')
        self.assertIn('TRANCADA', r['motivo'])

    def test_cancelada_nao_entra_mesmo_sem_atraso(self):
        Cancelamento.objects.create(matricula=self.matricula)
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'bloqueado')
        self.assertIn('CANCELADA', r['motivo'])

    def test_pagar_a_pendencia_libera_a_entrada_de_novo(self):
        c = self.cobranca(30)
        self.assertEqual(avaliar_situacao_financeira_aluno(self.aluno)['status'], 'bloqueado')
        c.paga = True
        c.save()
        self.assertEqual(avaliar_situacao_financeira_aluno(self.aluno)['status'], 'liberado')

    def test_formulario_de_matricula_do_app_alunos_nao_expoe_a_situacao(self):
        self.assertEqual(
            set(MatriculaFormDoApp().fields), {'aluno', 'plano', 'data_inicio', 'forma_pagamento'},
        )

class TarefaT06IdempotenciaTests(TestCase):
    """Critério do T06: rodar a geração de cobranças de novo NÃO duplica nada.
    Aqui o serviço é executado de verdade pela segunda vez (não basta
    não dar erro: é preciso provar que a contagem não mudou)."""

    def setUp(self):
        self.aluno = criar_aluno_valido()
        self.plano = Plano.objects.create(
            nome="Trimestral", periodicidade="trimestral", valor=Decimal('150.00'),
            taxa_adesao=Decimal('40.00'), dia_vencimento=10,
        )
        self.matricula = realizar_matricula(self.aluno, self.plano, date(2027, 2, 1), 'pix')

    def _snapshot(self):
        return sorted(
            matricula_cobranca for matricula_cobranca in
            self.matricula.cobrancas.values_list('id', 'tipo', 'competencia', 'valor', 'vencimento')
        )

    def test_rodar_o_servico_de_novo_nao_aumenta_a_quantidade(self):
        # 1 adesão + 3 mensalidades
        antes = self.matricula.cobrancas.count()
        self.assertEqual(antes, 4)

        criadas = gerar_cobrancas(self.matricula)

        self.assertEqual(criadas, 0)
        self.assertEqual(self.matricula.cobrancas.count(), antes)

    def test_cada_competencia_continua_aparecendo_uma_unica_vez(self):
        gerar_cobrancas(self.matricula)
        gerar_cobrancas(self.matricula)

        competencias = list(
            self.matricula.cobrancas.filter(tipo='mensalidade')
            .values_list('competencia', flat=True)
        )
        self.assertEqual(sorted(competencias), ['2027-02', '2027-03', '2027-04'])
        self.assertEqual(len(competencias), len(set(competencias)))
        self.assertEqual(self.matricula.cobrancas.filter(tipo='adesao').count(), 1)

    def test_rodar_de_novo_nao_altera_as_cobrancas_ja_geradas(self):
        antes = self._snapshot()
        gerar_cobrancas(self.matricula)
        self.assertEqual(self._snapshot(), antes)

    def test_rodar_de_novo_nao_mexe_em_cobranca_ja_paga(self):
        paga = self.matricula.cobrancas.filter(tipo='mensalidade').order_by('vencimento').first()
        paga.paga = True
        paga.save()
        gerar_cobrancas(self.matricula)
        paga.refresh_from_db()
        self.assertTrue(paga.paga)
        self.assertEqual(self.matricula.cobrancas.count(), 4)

    def test_se_faltar_uma_cobranca_rodar_de_novo_recria_so_a_que_faltava(self):
        self.matricula.cobrancas.filter(competencia='2027-03').delete()
        self.assertEqual(self.matricula.cobrancas.count(), 3)
        criadas = gerar_cobrancas(self.matricula)
        self.assertEqual(criadas, 1)
        self.assertEqual(self.matricula.cobrancas.count(), 4)

    def test_idempotencia_vale_por_matricula(self):
        outra = realizar_matricula(self.aluno, self.plano, date(2027, 2, 1), 'pix')
        gerar_cobrancas(outra)
        self.assertEqual(self.matricula.cobrancas.count(), 4)
        self.assertEqual(outra.cobrancas.count(), 4)


class VencimentoDaPrimeiraMensalidadeTests(TestCase):
    def setUp(self):
        self.aluno = criar_aluno_valido()
        self.plano = Plano.objects.create(
            nome="Mensal", periodicidade="mensal", valor=Decimal('100.00'),
            taxa_adesao=Decimal('0.00'), dia_vencimento=10,
        )

    def test_entrada_depois_do_dia_de_vencimento_nao_nasce_vencida(self):
        # Início no dia 20 com vencimento dia 10: não pode vencer no passado.
        matricula = realizar_matricula(self.aluno, self.plano, date(2027, 2, 20), 'pix')
        primeira = matricula.cobrancas.get(tipo='mensalidade')
        self.assertEqual(primeira.competencia, '2027-02')
        self.assertEqual(primeira.vencimento, date(2027, 2, 20))
        self.assertGreaterEqual(primeira.vencimento, matricula.data_inicio)

    def test_aluna_nao_fica_inadimplente_no_dia_da_matricula(self):
        inicio = date(2027, 2, 20)
        matricula = realizar_matricula(self.aluno, self.plano, inicio, 'pix')
        self.assertEqual(calcular_situacao(matricula, hoje=inicio), SituacaoMatricula.ATIVA)

    def test_entrada_antes_do_dia_de_vencimento_mantem_o_dia_do_plano(self):
        matricula = realizar_matricula(self.aluno, self.plano, date(2027, 2, 1), 'pix')
        self.assertEqual(matricula.cobrancas.get().vencimento, date(2027, 2, 10))

    def test_dia_31_em_mes_curto_usa_o_ultimo_dia(self):
        self.plano.dia_vencimento = 31
        self.plano.periodicidade = 'trimestral'
        self.plano.save()
        matricula = realizar_matricula(self.aluno, self.plano, date(2027, 3, 1), 'pix')
        vencimentos = [c.vencimento for c in matricula.cobrancas.order_by('vencimento')]
        self.assertEqual(vencimentos, [date(2027, 3, 31), date(2027, 4, 30), date(2027, 5, 31)])


def criar_cenario_t07():
    RegraFinanceira.obter()
    recepcionista = criar_usuario('recepcao_t07', Perfil.RECEPCAO)
    aluno = criar_aluno_valido()
    plano = Plano.objects.create(
        nome='Mensal T07', periodicidade='mensal', valor=Decimal('100.00'),
        dia_vencimento=10,
    )
    matricula = Matricula.objects.create(
        aluno=aluno, plano=plano,
        data_inicio=timezone.localdate() - timedelta(days=60),
        forma_pagamento='pix',
    )
    hoje = timezone.localdate()
    cobranca = Cobranca.objects.create(
        matricula=matricula,
        tipo='mensalidade',
        valor=Decimal('100.00'),
        vencimento=hoje - timedelta(days=10),
        competencia='2026-10',
    )
    return recepcionista, aluno, plano, matricula, cobranca, hoje


class TarefaT07RegistroPagamentoTests(TestCase):
    def setUp(self):
        (
            self.recepcionista, self.aluno, self.plano, self.matricula,
            self.cobranca, self.hoje,
        ) = criar_cenario_t07()
        self.url = reverse(
            'registrar_pagamento', kwargs={'cobranca_id': self.cobranca.pk},
        )
        self.client.force_login(self.recepcionista)

    def dados_pagamento(self, valor='102.33', data=None):
        return {
            'valor': valor,
            'data_pagamento': (data or self.hoje).isoformat(),
            'forma_pagamento': 'pix',
            'observacoes': '',
        }

    def test_somente_recepcao_pode_acessar_o_fluxo(self):
        self.assertTrue(
            reverse('listar_cobrancas_pagamento').startswith('/recepcao/pagamentos/'),
        )
        outro_cliente = Client()
        self.assertEqual(
            outro_cliente.get(reverse('listar_cobrancas_pagamento')).status_code,
            302,
        )
        financeiro = criar_usuario('financeiro_t07', Perfil.FINANCEIRO)
        outro_cliente.force_login(financeiro)
        resposta = outro_cliente.get(reverse('listar_cobrancas_pagamento'))
        self.assertRedirects(
            resposta, reverse('painel'), fetch_redirect_response=False,
        )

    def test_painel_recepcao_django_exibe_acesso_ao_registro_de_pagamento(self):
        resposta = self.client.get(reverse('painel_recepcao'))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, 'accounts/painel_recepcao.html')
        self.assertContains(
            resposta,
            f'href="{reverse("listar_cobrancas_pagamento")}"',
        )
        self.assertContains(resposta, self.aluno.nome)
        self.assertEqual(resposta.context['total_alunos'], 1)

    def test_pagamento_atrasado_mostra_total_antes_da_confirmacao(self):
        proxima = Cobranca.objects.create(
            matricula=self.matricula,
            tipo='mensalidade',
            valor=Decimal('100.00'),
            vencimento=self.hoje + timedelta(days=20),
            competencia='2026-11',
        )
        vencimento_proxima = proxima.vencimento
        resposta = self.client.post(self.url, self.dados_pagamento())
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['preview']['saldo_total'], Decimal('102.33'))
        self.assertEqual(Pagamento.objects.count(), 0)
        self.assertContains(resposta, 'Confira antes de confirmar')

        resposta = self.client.post(
            self.url, dict(self.dados_pagamento(), confirmar='1'),
        )
        self.assertRedirects(resposta, self.url)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'Cobrança quitada')
        self.assertContains(resposta, 'Estornar')
        pagamento = Pagamento.objects.get(cobranca=self.cobranca)
        self.assertEqual((pagamento.juros, pagamento.multa), (
            Decimal('0.33'), Decimal('2.00'),
        ))
        self.cobranca.refresh_from_db()
        self.assertTrue(self.cobranca.paga)
        self.assertEqual(
            calcular_situacao(self.matricula, hoje=self.hoje),
            SituacaoMatricula.ATIVA,
        )
        proxima.refresh_from_db()
        self.assertEqual(proxima.vencimento, vencimento_proxima)

    def test_pagamento_parcial_mantem_cobranca_aberta_com_saldo(self):
        pagamento = registrar_pagamento(
            self.cobranca, Decimal('50.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        self.assertEqual(pagamento.valor_pago, Decimal('50.00'))
        self.assertEqual(saldo_cobranca(self.cobranca, self.hoje), Decimal('52.33'))
        self.cobranca.refresh_from_db()
        self.assertFalse(self.cobranca.paga)

    def test_pagamento_antecipado_e_aceito_sem_mover_outros_vencimentos(self):
        self.cobranca.vencimento = self.hoje + timedelta(days=5)
        self.cobranca.save(update_fields=['vencimento'])
        proxima = Cobranca.objects.create(
            matricula=self.matricula,
            tipo='mensalidade',
            valor=Decimal('100.00'),
            vencimento=self.hoje + timedelta(days=35),
            competencia='2026-11',
        )
        vencimento_proxima = proxima.vencimento

        pagamento = registrar_pagamento(
            self.cobranca, Decimal('100.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )

        self.assertEqual(pagamento.juros, Decimal('0.00'))
        self.assertEqual(pagamento.multa, Decimal('0.00'))
        self.cobranca.refresh_from_db()
        proxima.refresh_from_db()
        self.assertTrue(self.cobranca.paga)
        self.assertEqual(proxima.vencimento, vencimento_proxima)

    def test_estorno_preserva_pagamento_e_reabre_saldo_com_motivo(self):
        pagamento = registrar_pagamento(
            self.cobranca, Decimal('102.33'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )

        estorno = registrar_estorno(
            pagamento, Decimal('102.33'), 'Lançamento feito por engano',
            self.recepcionista,
        )

        self.assertEqual(estorno.motivo, 'Lançamento feito por engano')
        self.assertTrue(Pagamento.objects.filter(pk=pagamento.pk).exists())
        self.assertEqual(saldo_cobranca(self.cobranca, self.hoje), Decimal('102.33'))
        self.cobranca.refresh_from_db()
        self.assertFalse(self.cobranca.paga)

    
    def test_estorno_integral_permite_pagar_novamente(self):
        # 1. Registra o pagamento integral da cobrança.
        pagamento = registrar_pagamento(
            self.cobranca,
            Decimal('102.33'),
            'pix',
            data_pagamento=self.hoje,
            usuario=self.recepcionista,
        )

        self.cobranca.refresh_from_db()

        print("\n--- DIAGNÓSTICO DO PAGAMENTO ---")
        print("Data de hoje:", self.hoje)
        print("Vencimento:", self.cobranca.vencimento)
        print("Valor da cobrança:", self.cobranca.valor)
        print("Valor registrado:", pagamento.valor_pago)
        print("Principal aplicado:", pagamento.principal_aplicado)
        print("Juros registrados:", pagamento.juros)
        print("Multa registrada:", pagamento.multa)
        print("Saldo na data do teste:", saldo_cobranca(self.cobranca, self.hoje))
        print("Saldo na data atual:", saldo_cobranca(self.cobranca))
        print("Cobrança marcada como paga:", self.cobranca.paga)

        self.cobranca.refresh_from_db()

        valor_paga = self.cobranca.paga

        print("Valor:", repr(valor_paga))
        print("Tipo:", type(valor_paga))
        print("É True:", valor_paga is True)

        self.assertIs(valor_paga, True)

        self.cobranca.refresh_from_db()
        self.assertTrue(self.cobranca.paga)
        self.assertEqual(
            saldo_cobranca(self.cobranca, self.hoje),
            Decimal('0.00'),
        )

        # 2. Estorna integralmente o pagamento.
        registrar_estorno(
            pagamento,
            Decimal('102.33'),
            'Teste de estorno integral',
            self.recepcionista,
        )

        self.cobranca.refresh_from_db()
        self.assertFalse(self.cobranca.paga)
        self.assertEqual(
            saldo_cobranca(self.cobranca, self.hoje),
            Decimal('102.33'),
        )

        # 3. Registra novamente o pagamento.
        novo_pagamento = registrar_pagamento(
            self.cobranca,
            Decimal('102.33'),
            'pix',
            data_pagamento=self.hoje,
            usuario=self.recepcionista,
        )

        self.cobranca.refresh_from_db()
        self.assertTrue(self.cobranca.paga)
        self.assertEqual(
            saldo_cobranca(self.cobranca, self.hoje),
            Decimal('0.00'),
        )

        # O pagamento original e o novo continuam no histórico.
        self.assertTrue(
            Pagamento.objects.filter(pk=pagamento.pk).exists()
        )
        self.assertTrue(
            Pagamento.objects.filter(pk=novo_pagamento.pk).exists()
        )
        self.assertEqual(
            Estorno.objects.filter(pagamento=pagamento).count(),
            1,
        )

    def test_estorno_parcial_nao_ultrapassa_o_valor_original(self):
        pagamento = registrar_pagamento(
            self.cobranca, Decimal('1.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        primeiro_estorno = registrar_estorno(
            pagamento, Decimal('0.25'), 'Primeiro estorno parcial',
            self.recepcionista,
        )
        segundo_estorno = registrar_estorno(
            pagamento, Decimal('0.25'), 'Segundo estorno parcial',
            self.recepcionista,
        )
        self.assertEqual(
            primeiro_estorno.principal_estornado
            + primeiro_estorno.juros_estornados
            + primeiro_estorno.multa_estornada,
            primeiro_estorno.valor,
        )
        self.assertEqual(
            segundo_estorno.principal_estornado
            + segundo_estorno.juros_estornados
            + segundo_estorno.multa_estornada,
            segundo_estorno.valor,
        )
        self.assertEqual(total_estornado(pagamento), Decimal('0.50'))
        self.assertEqual(
            [pagamento.ordem_evento, primeiro_estorno.ordem_evento,
             segundo_estorno.ordem_evento],
            [1, 2, 3],
        )

    def test_pagar_estornar_pagar_preserva_ordem_com_timestamps_iguais(self):
        instante = timezone.now()
        pagamento = registrar_pagamento(
            self.cobranca, Decimal('102.33'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        estorno = registrar_estorno(
            pagamento, Decimal('102.33'), 'Estorno de teste',
            self.recepcionista,
        )
        novo_pagamento = registrar_pagamento(
            self.cobranca, Decimal('102.33'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        Pagamento.objects.filter(pk__in=[pagamento.pk, novo_pagamento.pk]).update(
            criado_em=instante,
        )
        Estorno.objects.filter(pk=estorno.pk).update(criado_em=instante)

        self.assertEqual(
            [pagamento.ordem_evento, estorno.ordem_evento, novo_pagamento.ordem_evento],
            [1, 2, 3],
        )
        self.assertEqual(
            Pagamento.objects.get(pk=pagamento.pk).criado_em,
            Estorno.objects.get(pk=estorno.pk).criado_em,
        )
        self.assertEqual(
            Estorno.objects.get(pk=estorno.pk).criado_em,
            Pagamento.objects.get(pk=novo_pagamento.pk).criado_em,
        )
        self.assertEqual(saldo_cobranca(self.cobranca, self.hoje), Decimal('0.00'))

    def test_data_contabil_precede_sequencia_na_ordem_dos_eventos(self):
        regras = RegraFinanceira.obter()
        regras.dias_tolerancia = 0
        regras.juros_diario = Decimal('1.000')
        regras.multa_atraso = Decimal('0.00')
        regras.save()
        self.cobranca.vencimento = self.hoje - timedelta(days=5)
        self.cobranca.save(update_fields=['vencimento'])

        Pagamento.objects.create(
            cobranca=self.cobranca,
            ordem_evento=1,
            valor_pago=Decimal('50.00'),
            data_pagamento=self.hoje - timedelta(days=2),
            forma_pagamento='pix',
            principal_aplicado=Decimal('50.00'),
            registrado_por_nome='Teste',
        )
        Pagamento.objects.create(
            cobranca=self.cobranca,
            ordem_evento=2,
            valor_pago=Decimal('25.00'),
            data_pagamento=self.hoje - timedelta(days=3),
            forma_pagamento='pix',
            principal_aplicado=Decimal('25.00'),
            registrado_por_nome='Teste',
        )
        self.cobranca.ultima_sequencia_evento = 2
        self.cobranca.save(update_fields=['ultima_sequencia_evento'])

        self.assertEqual(
            saldo_cobranca(self.cobranca, self.hoje),
            Decimal('28.25'),
        )

    def test_migration_reconstrui_sequencia_sem_empates_ambiguos(self):
        primeiro = registrar_pagamento(
            self.cobranca, Decimal('10.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        segundo = registrar_pagamento(
            self.cobranca, Decimal('10.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        instante = timezone.now()
        Pagamento.objects.filter(pk=primeiro.pk).update(
            criado_em=instante,
            ordem_evento=2,
        )
        Pagamento.objects.filter(pk=segundo.pk).update(
            criado_em=instante + timedelta(seconds=1),
            ordem_evento=1,
        )
        self.cobranca.ultima_sequencia_evento = 10
        self.cobranca.save(update_fields=['ultima_sequencia_evento'])

        migration = import_module(
            'financeiro.migrations.0007_sequencia_evento_por_cobranca',
        )
        apps = SimpleNamespace(
            get_model=lambda app_label, model_name: {
                'Cobranca': Cobranca,
                'Pagamento': Pagamento,
                'Estorno': Estorno,
            }[model_name],
        )
        migration.preencher_sequencias_historicas(
            apps, SimpleNamespace(connection=connection),
        )

        primeiro.refresh_from_db()
        segundo.refresh_from_db()
        self.cobranca.refresh_from_db()
        self.assertEqual((primeiro.ordem_evento, segundo.ordem_evento), (1, 2))
        self.assertEqual(self.cobranca.ultima_sequencia_evento, 2)

    def test_migration_recusa_timestamps_historicos_ambiguos_sem_alterar_ordem(self):
        pagamento = registrar_pagamento(
            self.cobranca, Decimal('10.00'), 'pix',
            data_pagamento=self.hoje, usuario=self.recepcionista,
        )
        estorno = registrar_estorno(
            pagamento, Decimal('1.00'), 'Estorno para teste de migração',
            self.recepcionista,
        )
        instante = timezone.now()
        Pagamento.objects.filter(pk=pagamento.pk).update(criado_em=instante)
        Estorno.objects.filter(pk=estorno.pk).update(criado_em=instante)
        ordens_anteriores = (pagamento.ordem_evento, estorno.ordem_evento)
        migration = import_module(
            'financeiro.migrations.0007_sequencia_evento_por_cobranca',
        )
        apps = SimpleNamespace(
            get_model=lambda app_label, model_name: {
                'Cobranca': Cobranca,
                'Pagamento': Pagamento,
                'Estorno': Estorno,
            }[model_name],
        )

        with self.assertRaisesRegex(RuntimeError, 'timestamp de criação idênticos'):
            migration.preencher_sequencias_historicas(
                apps, SimpleNamespace(connection=connection),
            )

        pagamento.refresh_from_db()
        estorno.refresh_from_db()
        self.assertEqual(
            (pagamento.ordem_evento, estorno.ordem_evento),
            ordens_anteriores,
        )

    def test_nao_permite_valor_maior_que_saldo_ou_data_futura(self):
        resposta = self.client.post(self.url, self.dados_pagamento('103.00'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Pagamento.objects.count(), 0)

        with self.assertRaises(ValidationError):
            registrar_pagamento(
                self.cobranca, Decimal('1.00'), 'pix',
                data_pagamento=self.hoje + timedelta(days=1),
                usuario=self.recepcionista,
            )


class TarefaT07SequenciaConcorrenteTests(TransactionTestCase):
    def setUp(self):
        (
            self.recepcionista, _, _, _, self.cobranca, self.hoje,
        ) = criar_cenario_t07()

    def test_pagamento_e_estorno_concorrentes_preservam_sequencia_e_saldo(self):
        if connection.vendor != 'postgresql':
            self.skipTest("Teste de bloqueio concorrente requer PostgreSQL.")

        pagamento_original = registrar_pagamento(
            self.cobranca,
            Decimal('50.00'),
            'pix',
            data_pagamento=self.hoje,
            usuario=self.recepcionista,
        )
        barreira = threading.Barrier(2)
        erros = []

        def registrar_pagamento_concorrente():
            close_old_connections()
            try:
                usuario = User.objects.get(pk=self.recepcionista.pk)
                barreira.wait(timeout=10)
                registrar_pagamento(
                    self.cobranca,
                    Decimal('50.00'),
                    'pix',
                    data_pagamento=self.hoje,
                    usuario=usuario,
                )
            except Exception as erro:
                erros.append(erro)
            finally:
                close_old_connections()

        def registrar_estorno_concorrente():
            close_old_connections()
            try:
                usuario = User.objects.get(pk=self.recepcionista.pk)
                barreira.wait(timeout=10)
                registrar_estorno(
                    pagamento_original,
                    Decimal('50.00'),
                    'Estorno concorrente de teste',
                    usuario,
                )
            except Exception as erro:
                erros.append(erro)
            finally:
                close_old_connections()

        threads = [
            threading.Thread(target=registrar_pagamento_concorrente, daemon=True),
            threading.Thread(target=registrar_estorno_concorrente, daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(erros, [])
        sequencias_pagamentos = Pagamento.objects.filter(
            cobranca=self.cobranca,
        ).values_list('ordem_evento', flat=True)
        sequencias_estornos = Estorno.objects.filter(
            pagamento__cobranca=self.cobranca,
        ).values_list('ordem_evento', flat=True)
        self.assertEqual(
            sorted([*sequencias_pagamentos, *sequencias_estornos]),
            [1, 2, 3],
        )
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.ultima_sequencia_evento, 3)
        self.assertEqual(
            saldo_cobranca(self.cobranca, self.hoje),
            Decimal('52.33'),
        )


class TarefaT07MigrationExecutorTests(TransactionTestCase):
    def test_migration_0007_ambiguo_faz_rollback_de_schema_e_dados(self):
        if connection.vendor != 'postgresql':
            self.skipTest("Verificação de rollback DDL requer PostgreSQL.")

        (
            recepcionista, _, _, _, cobranca, hoje,
        ) = criar_cenario_t07()
        pagamento = registrar_pagamento(
            cobranca,
            Decimal('102.33'),
            'pix',
            data_pagamento=hoje,
            usuario=recepcionista,
        )
        estorno = registrar_estorno(
            pagamento,
            Decimal('102.33'),
            'Estorno para teste real de migration',
            recepcionista,
        )
        pagamento_id = pagamento.pk
        estorno_id = estorno.pk
        cobranca_id = cobranca.pk
        migrate_from = [('financeiro', '0006_pagamento_estorno')]
        migrate_to = [('financeiro', '0007_sequencia_evento_por_cobranca')]
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()

        try:
            executor.migrate(migrate_from)
            apps_0006 = executor.loader.project_state(migrate_from).apps
            PagamentoHistorico = apps_0006.get_model('financeiro', 'Pagamento')
            EstornoHistorico = apps_0006.get_model('financeiro', 'Estorno')
            instante_ambiguo = timezone.now()
            PagamentoHistorico.objects.filter(pk=pagamento_id).update(
                criado_em=instante_ambiguo,
            )
            EstornoHistorico.objects.filter(pk=estorno_id).update(
                criado_em=instante_ambiguo,
            )

            dados_pagamento_antes = PagamentoHistorico.objects.filter(
                pk=pagamento_id,
            ).values_list(
                'cobranca_id', 'valor_pago', 'data_pagamento', 'criado_em',
            ).get()
            dados_estorno_antes = EstornoHistorico.objects.filter(
                pk=estorno_id,
            ).values_list(
                'pagamento_id', 'valor', 'data_estorno', 'criado_em',
            ).get()

            with self.assertRaisesRegex(
                RuntimeError,
                'timestamp de criação idênticos',
            ):
                MigrationExecutor(connection).migrate(migrate_to)

            self.assertNotIn(
                ('financeiro', '0007_sequencia_evento_por_cobranca'),
                MigrationRecorder(connection).applied_migrations(),
            )
            with connection.cursor() as cursor:
                cobranca_colunas = {
                    coluna.name
                    for coluna in connection.introspection.get_table_description(
                        cursor, 'financeiro_cobranca',
                    )
                }
                pagamento_colunas = {
                    coluna.name
                    for coluna in connection.introspection.get_table_description(
                        cursor, 'financeiro_pagamento',
                    )
                }
                estorno_colunas = {
                    coluna.name
                    for coluna in connection.introspection.get_table_description(
                        cursor, 'financeiro_estorno',
                    )
                }
            self.assertNotIn('ultima_sequencia_evento', cobranca_colunas)
            self.assertNotIn('ordem_evento', pagamento_colunas)
            self.assertNotIn('ordem_evento', estorno_colunas)

            apps_apos_falha = MigrationExecutor(
                connection,
            ).loader.project_state(migrate_from).apps
            PagamentoAposFalha = apps_apos_falha.get_model(
                'financeiro', 'Pagamento',
            )
            EstornoAposFalha = apps_apos_falha.get_model(
                'financeiro', 'Estorno',
            )
            self.assertEqual(
                PagamentoAposFalha.objects.filter(pk=pagamento_id).values_list(
                    'cobranca_id', 'valor_pago', 'data_pagamento', 'criado_em',
                ).get(),
                dados_pagamento_antes,
            )
            self.assertEqual(
                EstornoAposFalha.objects.filter(pk=estorno_id).values_list(
                    'pagamento_id', 'valor', 'data_estorno', 'criado_em',
                ).get(),
                dados_estorno_antes,
            )
            self.assertTrue(
                apps_apos_falha.get_model(
                    'financeiro', 'Cobranca',
                ).objects.filter(pk=cobranca_id).exists(),
            )
        finally:
            migrations_aplicadas = MigrationRecorder(
                connection,
            ).applied_migrations()
            if ('financeiro', '0007_sequencia_evento_por_cobranca') not in migrations_aplicadas:
                estado_0006 = MigrationExecutor(
                    connection,
                ).loader.project_state(migrate_from).apps
                EstornoHistorico = estado_0006.get_model(
                    'financeiro', 'Estorno',
                )
                timestamp_atual = EstornoHistorico.objects.filter(
                    pk=estorno_id,
                ).values_list('criado_em', flat=True).get()
                EstornoHistorico.objects.filter(pk=estorno_id).update(
                    criado_em=timestamp_atual + timedelta(microseconds=1),
                )
            MigrationExecutor(connection).migrate(latest_targets)

class TarefaT17CancelamentoTests(TestCase):
    """Cancelar a matrícula com a multa certa.

    Plano semestral, R$ 100/mês, fidelidade de 6 meses, multa de 10%, vencimento
    dia 10. Matrícula iniciada em 01/01/2027: fidelidade até 01/07/2027 (181 dias).
    """

    def setUp(self):
        RegraFinanceira.obter()
        self.inicio = date(2027, 1, 1)
        self.hoje = date(2027, 4, 1)   # faltam 91 de 181 dias
        self.plano = Plano.objects.create(
            nome='Semestral fiel', periodicidade='semestral', valor=Decimal('100.00'),
            dia_vencimento=10, fidelidade_meses=6, multa_cancelamento=Decimal('10.00'),
        )
        self.matricula = realizar_matricula(criar_aluno_valido(), self.plano, self.inicio, 'pix')

    def cancelar(self, motivo='Mudou de cidade', **kw):
        from .servicos import cancelar_matricula
        kw.setdefault('hoje', self.hoje)
        return cancelar_matricula(self.matricula, motivo, **kw)

    def competencia(self, mes):
        return self.matricula.cobrancas.get(competencia=f'2027-{mes:02d}')

    # ---- cálculo da multa -------------------------------------------
    def test_multa_e_proporcional_ao_tempo_restante(self):
        from .servicos import calcular_multa_cancelamento
        # 600 (contrato) x 10% x 91/181 = 30,17
        r = calcular_multa_cancelamento(self.matricula, self.hoje)
        self.assertTrue(r['em_fidelidade'])
        self.assertEqual((r['dias_restantes'], r['dias_totais']), (91, 181))
        self.assertEqual(r['multa'], Decimal('30.17'))

    def test_multa_cheia_no_primeiro_dia_e_menor_depois(self):
        from .servicos import calcular_multa_cancelamento
        cheia = calcular_multa_cancelamento(self.matricula, self.inicio)['multa']
        meio = calcular_multa_cancelamento(self.matricula, self.hoje)['multa']
        fim = calcular_multa_cancelamento(self.matricula, date(2027, 6, 30))['multa']
        self.assertEqual(cheia, Decimal('60.00'))
        self.assertTrue(cheia > meio > fim > 0)

    def test_sem_multa_quando_a_fidelidade_ja_acabou(self):
        from .servicos import calcular_multa_cancelamento
        for dia in (date(2027, 7, 1), date(2028, 1, 1)):
            r = calcular_multa_cancelamento(self.matricula, dia)
            self.assertFalse(r['em_fidelidade'])
            self.assertEqual(r['multa'], Decimal('0.00'))

    def test_sem_multa_em_plano_sem_fidelidade(self):
        from .servicos import calcular_multa_cancelamento
        self.plano.fidelidade_meses = 0
        self.plano.save()
        self.matricula.refresh_from_db()
        self.assertEqual(calcular_multa_cancelamento(self.matricula, self.hoje)['multa'], Decimal('0.00'))
        resultado = self.cancelar()
        self.assertIsNone(resultado['cobranca_multa'])
        self.assertFalse(self.matricula.cobrancas.filter(tipo='multa_cancelamento').exists())

    # ---- o cancelamento ---------------------------------------------
    def test_cancelamento_registra_data_e_motivo(self):
        self.cancelar(motivo='  Mudou de cidade  ')
        c = Cancelamento.objects.get(matricula=self.matricula)
        self.assertEqual(c.data, self.hoje)
        self.assertEqual(c.motivo, 'Mudou de cidade')

    def test_motivo_e_obrigatorio(self):
        for motivo in ('', '   ', None):
            with self.assertRaises(ValidationError):
                self.cancelar(motivo=motivo)
        self.assertFalse(Cancelamento.objects.exists())

    def test_matricula_passa_a_cancelada(self):
        self.cancelar()
        self.assertEqual(calcular_situacao(self.matricula, hoje=self.hoje), SituacaoMatricula.CANCELADA)

    def test_nao_cancela_duas_vezes(self):
        self.cancelar()
        with self.assertRaisesMessage(ValidationError, 'já está cancelada'):
            self.cancelar()
        self.assertEqual(self.matricula.cobrancas.filter(tipo='multa_cancelamento').count(), 1)

    def test_multa_vira_cobranca_com_vencimento(self):
        r = self.cancelar()
        multa = r['cobranca_multa']
        self.assertEqual(multa.tipo, 'multa_cancelamento')
        self.assertEqual(multa.valor, Decimal('30.17'))
        self.assertEqual(multa.matricula, self.matricula)
        self.assertEqual(multa.vencimento, self.hoje)
        self.assertFalse(multa.paga)
        self.assertFalse(multa.cancelada)

    def test_multa_e_paga_como_qualquer_outra_cobranca(self):
        multa = self.cancelar()['cobranca_multa']
        hoje_real = timezone.localdate()
        pagamento = registrar_pagamento(
            multa, Decimal('30.17'), 'pix', data_pagamento=multa.vencimento if multa.vencimento <= hoje_real else hoje_real,
        )
        multa.refresh_from_db()
        self.assertTrue(multa.paga)
        self.assertEqual(pagamento.valor_pago, Decimal('30.17'))

    def test_futuras_nao_vencidas_sao_canceladas(self):
        r = self.cancelar()
        for mes in (4, 5, 6):   # 10/04, 10/05, 10/06: ainda não venceram
            c = self.competencia(mes)
            self.assertTrue(c.cancelada, mes)
            self.assertFalse(c.paga)
        self.assertEqual(len(r['canceladas']), 3)

    def test_vencidas_e_nao_pagas_continuam_como_divida(self):
        r = self.cancelar()
        for mes in (1, 2, 3):   # venceram antes de 01/04
            c = self.competencia(mes)
            self.assertFalse(c.cancelada, mes)
            self.assertFalse(c.paga, mes)
            self.assertGreaterEqual(saldo_cobranca(c, self.hoje), Decimal('100.00'))
        self.assertEqual(len(r['dividas']), 3)
        self.assertGreaterEqual(r['total_dividas'], Decimal('300.00'))

    def test_cobranca_que_vence_no_dia_do_cancelamento_e_futura(self):
        # "Vencida" é vencimento ANTES de hoje, como no resto do sistema.
        r = self.cancelar(hoje=date(2027, 4, 10))
        self.assertTrue(self.competencia(4).cancelada)
        self.assertFalse(self.competencia(3).cancelada)
        self.assertEqual(len(r['canceladas']), 3)

    def test_cobranca_ja_paga_nao_e_cancelada(self):
        c = self.competencia(5)
        c.paga = True
        c.save()
        self.cancelar()
        c.refresh_from_db()
        self.assertFalse(c.cancelada)

    def test_futura_com_pagamento_e_cancelada_mas_sinalizada(self):
        # Pagamento antecipado de uma mensalidade que vence no futuro.
        hoje_real = timezone.localdate()
        matricula = realizar_matricula(
            criar_aluno_valido(), self.plano, hoje_real, 'pix',
        )
        futura = matricula.cobrancas.order_by('-vencimento').first()
        registrar_pagamento(futura, Decimal('50.00'), 'pix', data_pagamento=hoje_real)
        from .servicos import cancelar_matricula
        r = cancelar_matricula(matricula, 'Desistiu', hoje=hoje_real)
        futura.refresh_from_db()
        self.assertTrue(futura.cancelada)
        self.assertIn(futura, r['canceladas_com_pagamento'])
        self.assertEqual(futura.pagamentos.count(), 1)   # o pagamento não some

    def test_nenhuma_cobranca_nova_depois_do_cancelamento(self):
        self.cancelar()
        total = self.matricula.cobrancas.count()
        self.assertEqual(gerar_cobrancas(self.matricula), 0)
        self.assertEqual(self.matricula.cobrancas.count(), total)

    def test_cobranca_cancelada_nao_aceita_pagamento(self):
        self.cancelar()
        with self.assertRaisesMessage(ValidationError, 'cancelada'):
            registrar_pagamento(self.competencia(6), Decimal('100.00'), 'pix', data_pagamento=timezone.localdate())

    def test_cobranca_cancelada_nao_vira_atraso_depois(self):
        from .servicos import calcular_situacao
        self.cancelar()
        # Muito depois: a cobrança cancelada não pode voltar como atrasada.
        atrasos = self.matricula.cobrancas.filter(paga=False, cancelada=False, vencimento__lt=date(2028, 1, 1))
        self.assertNotIn(self.competencia(6), atrasos)
        self.assertEqual(calcular_situacao(self.matricula, hoje=date(2028, 1, 1)), SituacaoMatricula.CANCELADA)

    def test_previsao_nao_grava_nada(self):
        from .servicos import previsao_cancelamento
        p = previsao_cancelamento(self.matricula, self.hoje)
        self.assertEqual(p['multa']['multa'], Decimal('30.17'))
        self.assertEqual(len(p['a_cancelar']), 3)
        self.assertEqual(len(p['dividas']), 3)
        self.assertFalse(Cancelamento.objects.exists())
        self.assertFalse(self.matricula.cobrancas.filter(cancelada=True).exists())

    # ---- o valor mostrado é o valor cobrado --------------------------
    def test_valor_mostrado_igual_ao_calculado_confirma(self):
        r = self.cancelar(multa_esperada=Decimal('30.17'))
        self.assertEqual(r['cobranca_multa'].valor, Decimal('30.17'))

    def test_valor_mostrado_diferente_nao_cancela_nada(self):
        with self.assertRaises(ValidationError) as ctx:
            self.cancelar(multa_esperada=Decimal('99.99'))
        self.assertEqual(ctx.exception.code, 'multa_divergente')
        self.assertFalse(Cancelamento.objects.exists())
        self.assertFalse(self.matricula.cobrancas.filter(cancelada=True).exists())
        self.assertFalse(self.matricula.cobrancas.filter(tipo='multa_cancelamento').exists())


class TarefaT17TelaRecepcaoTests(TestCase):
    """A recepção vê o valor da multa ANTES de confirmar; só o POST cancela."""

    def setUp(self):
        RegraFinanceira.obter()
        self.recepcao = criar_usuario('recepcao_t17', 'recepcao')
        self.client = Client()
        self.client.force_login(self.recepcao)
        self.hoje = timezone.localdate()
        self.plano = Plano.objects.create(
            nome='Anual fiel', periodicidade='mensal', valor=Decimal('100.00'),
            dia_vencimento=10, fidelidade_meses=12, multa_cancelamento=Decimal('20.00'),
        )
        self.aluno = criar_aluno_valido()
        self.matricula = realizar_matricula(self.aluno, self.plano, self.hoje, 'pix')
        self.url = reverse('cancelar_matricula', args=[self.matricula.pk])

    def test_get_mostra_a_multa_e_nao_grava(self):
        # Matrícula iniciada hoje: fidelidade inteira pela frente = 1200 x 20% = 240,00
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '240,00')
        self.assertContains(r, 'Confirmar cancelamento')
        self.assertFalse(Cancelamento.objects.exists())
        self.assertFalse(Cobranca.objects.filter(tipo='multa_cancelamento').exists())

    def test_post_confirma_e_cria_multa_como_cobranca(self):
        r = self.client.post(self.url, {'motivo': 'Mudou de cidade', 'multa_exibida': '240.00'}, follow=True)
        self.assertContains(r, 'cancelada em')
        self.assertTrue(Cancelamento.objects.filter(matricula=self.matricula, motivo='Mudou de cidade').exists())
        multa = Cobranca.objects.get(matricula=self.matricula, tipo='multa_cancelamento')
        self.assertEqual(multa.valor, Decimal('240.00'))

    def test_post_sem_motivo_nao_cancela(self):
        r = self.client.post(self.url, {'motivo': '  ', 'multa_exibida': '240.00'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Informe o motivo')
        self.assertFalse(Cancelamento.objects.exists())

    def test_post_sem_o_valor_mostrado_nao_cancela(self):
        r = self.client.post(self.url, {'motivo': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Cancelamento.objects.exists())

    def test_valor_mostrado_desatualizado_pede_conferencia(self):
        r = self.client.post(self.url, {'motivo': 'Mudou', 'multa_exibida': '10.00'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'multa mudou')
        self.assertContains(r, 'Mudou')           # o motivo digitado não se perde
        self.assertContains(r, '240,00')           # mostra o valor atual
        self.assertFalse(Cancelamento.objects.exists())

    def test_matricula_cancelada_mostra_resumo_e_nao_cancela_de_novo(self):
        self.client.post(self.url, {'motivo': 'x', 'multa_exibida': '240.00'})
        r = self.client.get(self.url)
        self.assertContains(r, 'Matrícula cancelada')
        self.assertContains(r, 'Registrar pagamento')   # a multa está em aberto
        r = self.client.post(self.url, {'motivo': 'y', 'multa_exibida': '0'}, follow=True)
        self.assertContains(r, 'já está cancelada')
        self.assertEqual(Cobranca.objects.filter(tipo='multa_cancelamento').count(), 1)

    def test_cobrancas_canceladas_somem_da_lista_de_pagamento_e_a_multa_aparece(self):
        self.client.post(self.url, {'motivo': 'x', 'multa_exibida': '240.00'})
        r = self.client.get(reverse('listar_cobrancas_pagamento'))
        self.assertContains(r, 'Multa de Cancelamento')
        self.assertEqual(r.content.decode().count('Mensalidade'), 0)

    def test_busca_lista_matriculas_nao_canceladas(self):
        r = self.client.get(reverse('buscar_matricula_cancelamento'), {'q': self.aluno.nome})
        self.assertContains(r, self.url)
        self.client.post(self.url, {'motivo': 'x', 'multa_exibida': '240.00'})
        r = self.client.get(reverse('buscar_matricula_cancelamento'), {'q': self.aluno.nome})
        self.assertNotContains(r, self.url)

    def test_so_a_recepcao_cancela(self):
        outro = Client()
        outro.force_login(criar_usuario('prof_t17', 'professor'))
        r = outro.post(self.url, {'motivo': 'x', 'multa_exibida': '240.00'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Cancelamento.objects.exists())
        self.assertEqual(Client().get(self.url).status_code, 302)
    
class TarefaT18RenovacaoTests(TestCase):
    """Renovação no fim da vigência.

    Plano semestral, R$ 100/mês, vencimento dia 10. Matrícula iniciada em
    01/01/2027: o ciclo 1 cobre jan-jun e a vigência termina em 01/07/2027.
    """

    def setUp(self):
        RegraFinanceira.obter()
        self.inicio = date(2027, 1, 1)
        self.fim1 = date(2027, 7, 1)
        self.plano = Plano.objects.create(
            nome='Semestral auto', periodicidade='semestral', valor=Decimal('100.00'),
            dia_vencimento=10, taxa_adesao=Decimal('30.00'), renovacao_automatica=True,
        )
        self.matricula = realizar_matricula(criar_aluno_valido(), self.plano, self.inicio, 'pix')

    def renovar(self, matricula=None, hoje=None, **kw):
        from .servicos import renovar_matricula
        return renovar_matricula(matricula or self.matricula, hoje=hoje or self.fim1, **kw)

    def mensalidades(self, matricula=None):
        m = matricula or self.matricula
        return list(m.cobrancas.filter(tipo='mensalidade').order_by('competencia'))

    # ---- o plano define o tipo ---------------------------------------
    def test_plano_define_se_a_renovacao_e_automatica(self):
        self.assertTrue(self.plano.renovacao_automatica)
        manual = Plano.objects.create(nome='Manual', periodicidade='mensal', valor=Decimal('50.00'))
        self.assertFalse(manual.renovacao_automatica)   # padrão: com confirmação

    # ---- ciclo seguinte, mesmas regras ------------------------------
    def test_renovacao_gera_as_cobrancas_do_ciclo_seguinte(self):
        r = self.renovar(automatica=True)
        self.assertTrue(r['renovada'])
        self.assertEqual(r['cobrancas_criadas'], 6)
        self.assertEqual(r['renovacao'].ciclo, 2)
        self.assertEqual((r['renovacao'].inicio, r['renovacao'].fim), (self.fim1, date(2028, 1, 1)))
        comps = [c.competencia for c in self.mensalidades()]
        self.assertEqual(comps, [f'2027-{m:02d}' for m in range(1, 13)])

    def test_cobrancas_novas_seguem_as_mesmas_regras(self):
        self.renovar(automatica=True)
        ciclo2 = [c for c in self.mensalidades() if c.competencia >= '2027-07']
        self.assertEqual([c.valor for c in ciclo2], [Decimal('100.00')] * 6)
        self.assertEqual(
            [c.vencimento for c in ciclo2],
            [date(2027, m, 10) for m in range(7, 13)],
        )
        self.assertTrue(all(not c.paga and not c.cancelada for c in ciclo2))

    def test_nunca_vence_antes_do_inicio_do_ciclo_como_no_ciclo_1(self):
        m = realizar_matricula(criar_aluno_valido(), self.plano, date(2027, 1, 15), 'pix')
        self.assertEqual(m.cobrancas.get(competencia='2027-01').vencimento, date(2027, 1, 15))
        from .servicos import renovar_matricula
        renovar_matricula(m, hoje=date(2027, 7, 15), automatica=True)
        self.assertEqual(m.cobrancas.get(competencia='2027-07').vencimento, date(2027, 7, 15))
        self.assertEqual(m.cobrancas.get(competencia='2027-08').vencimento, date(2027, 8, 10))

    def test_taxa_de_adesao_nao_se_repete(self):
        self.renovar(automatica=True)
        self.assertEqual(self.matricula.cobrancas.filter(tipo='adesao').count(), 1)

    def test_ciclo_seguinte_comeca_exatamente_onde_o_anterior_termina(self):
        self.renovar(automatica=True)
        from .servicos import fim_vigencia
        r2 = self.renovar(hoje=date(2028, 1, 1), automatica=True)
        self.assertEqual(r2['renovacao'].inicio, date(2028, 1, 1))
        self.assertEqual(fim_vigencia(self.matricula), date(2028, 7, 1))

    def test_dia_31_nao_deriva_entre_ciclos(self):
        mensal = Plano.objects.create(
            nome='Mensal auto', periodicidade='mensal', valor=Decimal('80.00'),
            dia_vencimento=31, renovacao_automatica=True,
        )
        m = realizar_matricula(criar_aluno_valido(), mensal, date(2027, 1, 31), 'pix')
        from .servicos import renovar_matricula, fim_vigencia
        fins = []
        for hoje in (date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)):
            renovar_matricula(m, hoje=hoje, automatica=True)
            fins.append(fim_vigencia(m))
        self.assertEqual(fins, [date(2027, 3, 31), date(2027, 4, 30), date(2027, 5, 31)])

    # ---- automática: sem ninguém clicar -------------------------------
    def test_automatica_acontece_sem_ninguem_clicar(self):
        from .servicos import renovar_automaticas
        resumo = renovar_automaticas(self.fim1)
        self.assertEqual((resumo['ciclos'], resumo['matriculas'], resumo['cobrancas']), (1, 1, 6))
        r = self.matricula.renovacoes.get()
        self.assertTrue(r.automatica)
        self.assertIsNone(r.confirmada_por)

    def test_automatica_nao_renova_antes_da_hora(self):
        from .servicos import renovar_automaticas
        resumo = renovar_automaticas(date(2027, 6, 30))
        self.assertEqual(resumo['ciclos'], 0)
        self.assertFalse(self.matricula.renovacoes.exists())

    def test_automatica_alcanca_ciclos_atrasados_sem_deixar_dia_de_fora(self):
        from .servicos import renovar_automaticas, fim_vigencia
        resumo = renovar_automaticas(date(2028, 2, 1))   # sistema ficou parado
        self.assertEqual(resumo['ciclos'], 2)
        self.assertEqual(
            [(r.inicio, r.fim) for r in self.matricula.renovacoes.all()],
            [(date(2027, 7, 1), date(2028, 1, 1)), (date(2028, 1, 1), date(2028, 7, 1))],
        )
        self.assertEqual(fim_vigencia(self.matricula), date(2028, 7, 1))

    def test_automatica_nao_toca_plano_com_confirmacao(self):
        from .servicos import renovar_automaticas
        manual = Plano.objects.create(
            nome='Manual', periodicidade='semestral', valor=Decimal('100.00'), dia_vencimento=10,
        )
        m = realizar_matricula(criar_aluno_valido(), manual, self.inicio, 'pix')
        renovar_automaticas(self.fim1)
        self.assertFalse(m.renovacoes.exists())

    def test_comando_renovar_matriculas(self):
        from django.core.management import call_command
        from io import StringIO
        saida = StringIO()
        call_command('renovar_matriculas', data='2027-07-01', stdout=saida)
        self.assertIn('1 ciclo(s) gerado(s)', saida.getvalue())
        self.assertEqual(self.matricula.renovacoes.count(), 1)

    # ---- rodar duas vezes não gera dois ciclos -------------------------
    def test_rodar_a_renovacao_duas_vezes_nao_gera_dois_ciclos(self):
        from .servicos import renovar_automaticas
        renovar_automaticas(self.fim1)
        total = self.matricula.cobrancas.count()
        resumo = renovar_automaticas(self.fim1)
        self.assertEqual(resumo['ciclos'], 0)
        self.assertEqual(self.matricula.renovacoes.count(), 1)
        self.assertEqual(self.matricula.cobrancas.count(), total)

    def test_renovar_a_mesma_matricula_duas_vezes_seguidas(self):
        a = self.renovar(automatica=True)
        b = self.renovar(automatica=True)
        self.assertTrue(a['renovada'])
        self.assertFalse(b['renovada'])
        self.assertEqual(self.matricula.renovacoes.count(), 1)
        self.assertEqual(len(self.mensalidades()), 12)

    def test_o_banco_recusa_ciclo_duplicado(self):
        from django.db import IntegrityError, transaction
        self.renovar(automatica=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Renovacao.objects.create(
                matricula=self.matricula, ciclo=2, inicio=self.fim1,
                fim=date(2028, 1, 1), meses_acumulados=12,
            )

    # ---- renovar não apaga nem altera dívida --------------------------
    def test_renovar_nao_apaga_nem_altera_divida_pendente(self):
        antes = {
            c.pk: (c.valor, c.vencimento, c.competencia, c.tipo, c.paga, c.cancelada)
            for c in self.matricula.cobrancas.all()
        }
        saldos_antes = {
            c.pk: saldo_cobranca(c, self.fim1) for c in self.matricula.cobrancas.all()
        }
        self.assertTrue(all(v > 0 for v in saldos_antes.values()))   # tudo em aberto
        self.renovar(automatica=True)
        for c in Cobranca.objects.filter(pk__in=antes):
            self.assertEqual(
                (c.valor, c.vencimento, c.competencia, c.tipo, c.paga, c.cancelada), antes[c.pk],
            )
            self.assertEqual(saldo_cobranca(c, self.fim1), saldos_antes[c.pk])

    def test_aluno_renova_devendo_e_continua_devendo(self):
        antes = calcular_situacao(self.matricula, hoje=self.fim1)
        self.assertEqual(antes, SituacaoMatricula.BLOQUEADA)   # jan-jun em atraso
        self.renovar(automatica=True)
        self.assertEqual(calcular_situacao(self.matricula, hoje=self.fim1), SituacaoMatricula.BLOQUEADA)
        # a mensalidade mais antiga em aberto continua sendo a de janeiro
        self.assertEqual(
            self.matricula.cobrancas.filter(tipo='mensalidade', paga=False, vencimento__lt=self.fim1)
            .order_by('vencimento').first().competencia, '2027-01',
        )

    def test_cobranca_vencida_paga_continua_paga_e_a_devida_continua_devida(self):
        c1 = self.matricula.cobrancas.get(competencia='2027-01')
        c1.paga = True
        c1.save()
        self.renovar(automatica=True)
        c1.refresh_from_db()
        self.assertTrue(c1.paga)
        self.assertFalse(self.matricula.cobrancas.get(competencia='2027-02').paga)

    # ---- cancelada não renova -----------------------------------------
    def test_matricula_cancelada_nao_renova(self):
        from .servicos import renovar_automaticas
        Cancelamento.objects.create(matricula=self.matricula, data=self.fim1)
        resumo = renovar_automaticas(self.fim1)
        self.assertEqual(resumo['ciclos'], 0)
        with self.assertRaisesMessage(ValidationError, 'cancelada'):
            self.renovar()
        self.assertEqual(len(self.mensalidades()), 6)

    def test_cancelar_matricula_renovada_cancela_as_futuras(self):
        from .servicos import cancelar_matricula
        self.renovar(automatica=True)
        cancelar_matricula(self.matricula, 'Desistiu', hoje=date(2027, 9, 1))
        self.assertTrue(self.matricula.cobrancas.get(competencia='2027-10').cancelada)
        self.assertFalse(self.matricula.cobrancas.get(competencia='2027-08').cancelada)  # vencida


class TarefaT18ConfirmacaoDaRecepcaoTests(TestCase):
    """Plano com confirmação: o painel avisa e a recepção confirma."""

    def setUp(self):
        RegraFinanceira.obter()
        self.hoje = timezone.localdate()
        self.plano = Plano.objects.create(
            nome='Trimestral manual', periodicidade='trimestral', valor=Decimal('90.00'),
            dia_vencimento=10, renovacao_automatica=False,
        )
        self.recepcao = criar_usuario('recepcao_t18', 'recepcao')
        self.client = Client()
        self.client.force_login(self.recepcao)

    def matricula_com_fim_em(self, dias):
        """Matrícula trimestral cuja vigência termina daqui a `dias` dias."""
        fim = self.hoje + timedelta(days=dias)
        inicio = fim - relativedelta(months=3)
        return realizar_matricula(criar_aluno_valido(), self.plano, inicio, 'pix')

    def test_painel_avisa_quais_estao_vencendo(self):
        from .servicos import renovacoes_a_vencer
        vencendo = self.matricula_com_fim_em(5)
        vencida = self.matricula_com_fim_em(-3)
        longe = self.matricula_com_fim_em(60)
        ids = [i['matricula'].pk for i in renovacoes_a_vencer(self.hoje)]
        self.assertEqual(ids, [vencida.pk, vencendo.pk])    # mais urgente primeiro
        self.assertNotIn(longe.pk, ids)

    def test_painel_nao_lista_plano_automatico_nem_cancelada(self):
        from .servicos import renovacoes_a_vencer
        auto = Plano.objects.create(
            nome='Auto', periodicidade='trimestral', valor=Decimal('90.00'), renovacao_automatica=True,
        )
        fim = self.hoje + timedelta(days=3)
        m_auto = realizar_matricula(criar_aluno_valido(), auto, fim - relativedelta(months=3), 'pix')
        m_canc = self.matricula_com_fim_em(3)
        Cancelamento.objects.create(matricula=m_canc)
        ids = [i['matricula'].pk for i in renovacoes_a_vencer(self.hoje)]
        self.assertNotIn(m_auto.pk, ids)
        self.assertNotIn(m_canc.pk, ids)

    def test_painel_da_recepcao_mostra_o_aviso(self):
        m = self.matricula_com_fim_em(5)
        r = self.client.get(reverse('painel_recepcao'))
        self.assertContains(r, 'renovação por confirmação vencendo')
        self.assertContains(r, reverse('listar_renovacoes'))
        self.assertContains(r, m.aluno.nome)

    def test_sem_renovacao_vencendo_nao_ha_aviso(self):
        self.matricula_com_fim_em(60)
        r = self.client.get(reverse('painel_recepcao'))
        self.assertNotContains(r, 'renovação por confirmação vencendo')

    def test_lista_mostra_a_matricula_e_o_botao(self):
        m = self.matricula_com_fim_em(5)
        r = self.client.get(reverse('listar_renovacoes'))
        self.assertContains(r, m.aluno.nome)
        self.assertContains(r, 'Confirmar renovação')
        self.assertContains(r, 'Vence em 5 dia(s)')

    def test_renovacao_manual_exige_confirmacao_nao_acontece_sozinha(self):
        from .servicos import renovar_automaticas
        m = self.matricula_com_fim_em(0)
        renovar_automaticas(self.hoje)
        self.assertFalse(m.renovacoes.exists())
        self.client.get(reverse('listar_renovacoes'))      # só olhar não renova
        self.assertFalse(m.renovacoes.exists())

    def test_confirmar_renova_e_registra_quem_confirmou(self):
        from .servicos import fim_vigencia
        m = self.matricula_com_fim_em(5)
        fim = fim_vigencia(m)
        r = self.client.post(
            reverse('confirmar_renovacao', args=[m.pk]), {'fim_vigencia': fim.isoformat()}, follow=True,
        )
        self.assertContains(r, 'renovada: ciclo 2')
        ren = m.renovacoes.get()
        self.assertFalse(ren.automatica)
        self.assertEqual(ren.confirmada_por, self.recepcao)
        self.assertEqual(ren.inicio, fim)
        self.assertEqual(m.cobrancas.filter(tipo='mensalidade').count(), 6)
        self.assertNotContains(self.client.get(reverse('listar_renovacoes')), m.aluno.nome)

    def test_clique_duplo_nao_gera_dois_ciclos(self):
        from .servicos import fim_vigencia
        m = self.matricula_com_fim_em(-40)       # vencida há mais de um ciclo
        fim = fim_vigencia(m)
        url = reverse('confirmar_renovacao', args=[m.pk])
        self.client.post(url, {'fim_vigencia': fim.isoformat()})
        r = self.client.post(url, {'fim_vigencia': fim.isoformat()}, follow=True)
        self.assertContains(r, 'já foi renovada')
        self.assertEqual(m.renovacoes.count(), 1)

    def test_confirmar_fora_da_janela_nao_renova(self):
        from .servicos import fim_vigencia
        m = self.matricula_com_fim_em(60)
        r = self.client.post(
            reverse('confirmar_renovacao', args=[m.pk]),
            {'fim_vigencia': fim_vigencia(m).isoformat()}, follow=True,
        )
        self.assertContains(r, 'ainda não está no período')
        self.assertFalse(m.renovacoes.exists())

    def test_confirmar_com_data_invalida_nao_renova(self):
        m = self.matricula_com_fim_em(5)
        self.client.post(reverse('confirmar_renovacao', args=[m.pk]), {'fim_vigencia': 'lixo'})
        self.assertFalse(m.renovacoes.exists())

    def test_confirmar_renovacao_nao_limpa_divida(self):
        m = self.matricula_com_fim_em(5)
        from .servicos import fim_vigencia
        devidas = list(m.cobrancas.filter(vencimento__lt=self.hoje, paga=False).values_list('pk', 'valor'))
        self.assertTrue(devidas)    # a matrícula nasceu há ~3 meses sem pagar
        self.client.post(
            reverse('confirmar_renovacao', args=[m.pk]), {'fim_vigencia': fim_vigencia(m).isoformat()},
        )
        depois = list(
            m.cobrancas.filter(pk__in=[d[0] for d in devidas], paga=False, cancelada=False)
            .values_list('pk', 'valor')
        )
        self.assertEqual(sorted(depois), sorted(devidas))

    def test_get_na_confirmacao_nao_renova(self):
        m = self.matricula_com_fim_em(5)
        self.client.get(reverse('confirmar_renovacao', args=[m.pk]))
        self.assertFalse(m.renovacoes.exists())

    def test_so_a_recepcao_ve_e_confirma(self):
        from .servicos import fim_vigencia
        m = self.matricula_com_fim_em(5)
        outro = Client()
        outro.force_login(criar_usuario('prof_t18', 'professor'))
        self.assertEqual(outro.get(reverse('listar_renovacoes')).status_code, 302)
        outro.post(reverse('confirmar_renovacao', args=[m.pk]), {'fim_vigencia': fim_vigencia(m).isoformat()})
        self.assertFalse(m.renovacoes.exists())
        self.assertEqual(Client().get(reverse('listar_renovacoes')).status_code, 302)


class TarefaT18PlanoTests(TestCase):
    def test_plano_tem_a_opcao_no_formulario_e_na_lista(self):
        from .forms import PlanoForm
        self.assertIn('renovacao_automatica', PlanoForm().fields)
        form = PlanoForm({
            'nome': 'Gold', 'modalidades_incluidas': 'Musculação', 'periodicidade': 'mensal',
            'valor': '99.90', 'fidelidade_meses': 0, 'multa_cancelamento': '0',
            'taxa_adesao': '0', 'dia_vencimento': 10, 'renovacao_automatica': 'on', 'ativo': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().renovacao_automatica)
        fin = Client()
        fin.force_login(criar_usuario('fin_t18', 'financeiro'))
        self.assertContains(fin.get(reverse('listar_planos')), 'Automática')


class TarefaT18RenovacaoSemCliqueTests(TestCase):
    """A renovação automática acontece sozinha: basta o sistema ser usado."""

    def setUp(self):
        from . import middleware
        RegraFinanceira.obter()
        middleware.reiniciar_estado()
        self.addCleanup(middleware.reiniciar_estado)
        self.hoje = timezone.localdate()
        self.plano = Plano.objects.create(
            nome='Trimestral auto', periodicidade='trimestral', valor=Decimal('90.00'),
            dia_vencimento=10, renovacao_automatica=True,
        )
        inicio = self.hoje - relativedelta(months=3)    # vigência que terminou hoje
        self.matricula = realizar_matricula(criar_aluno_valido(), self.plano, inicio, 'pix')
        self.client = Client()
        self.client.force_login(criar_usuario('rec_sem_clique', 'recepcao'))

    def test_esta_ligado_no_projeto_e_desligado_so_nos_testes(self):
        from django.conf import settings
        self.assertIn('financeiro.middleware.RenovacaoAutomaticaMiddleware', settings.MIDDLEWARE)
        self.assertFalse(settings.RENOVACAO_AUTOMATICA_NA_REQUISICAO)   # estamos em `manage.py test`

    def test_desligado_nao_renova(self):
        self.client.get(reverse('painel_recepcao'))
        self.assertFalse(self.matricula.renovacoes.exists())

    def test_primeira_requisicao_do_dia_renova_sozinha(self):
        with self.settings(RENOVACAO_AUTOMATICA_NA_REQUISICAO=True):
            self.client.get(reverse('painel_recepcao'))
        r = self.matricula.renovacoes.get()
        self.assertTrue(r.automatica)
        self.assertEqual(r.inicio, self.hoje)
        self.assertEqual(self.matricula.cobrancas.filter(tipo='mensalidade').count(), 6)

    def test_so_uma_varredura_por_dia_e_sem_duplicar(self):
        with self.settings(RENOVACAO_AUTOMATICA_NA_REQUISICAO=True):
            for _ in range(3):
                self.client.get(reverse('painel_recepcao'))
        self.assertEqual(self.matricula.renovacoes.count(), 1)
        self.assertEqual(self.matricula.cobrancas.filter(tipo='mensalidade').count(), 6)

    def test_dia_seguinte_varre_de_novo(self):
        from . import middleware
        with self.settings(RENOVACAO_AUTOMATICA_NA_REQUISICAO=True):
            self.client.get(reverse('painel_recepcao'))
            middleware._estado['dia'] = self.hoje - timedelta(days=1)   # "virou o dia"
            self.client.get(reverse('painel_recepcao'))
        self.assertEqual(self.matricula.renovacoes.count(), 1)   # nada a fazer, nada duplicado

    def test_nao_renova_plano_com_confirmacao(self):
        manual = Plano.objects.create(
            nome='Manual', periodicidade='trimestral', valor=Decimal('90.00'), dia_vencimento=10,
        )
        m = realizar_matricula(
            criar_aluno_valido(), manual, self.hoje - relativedelta(months=3), 'pix',
        )
        with self.settings(RENOVACAO_AUTOMATICA_NA_REQUISICAO=True):
            self.client.get(reverse('painel_recepcao'))
        self.assertFalse(m.renovacoes.exists())

    def test_falha_na_varredura_nao_derruba_a_tela(self):
        from unittest import mock
        from . import middleware
        with self.settings(RENOVACAO_AUTOMATICA_NA_REQUISICAO=True), \
                mock.patch('financeiro.servicos.renovar_automaticas', side_effect=RuntimeError('boom')), \
                self.assertLogs('financeiro.middleware', level='ERROR'):
            r = self.client.get(reverse('painel_recepcao'))
        self.assertEqual(r.status_code, 200)
        self.assertGreater(middleware._estado['nao_antes_de'], 0)   # espera antes de tentar de novo

    def test_varredura_nao_trava_quem_ainda_nao_venceu(self):
        from unittest import mock
        from .servicos import renovar_automaticas
        longe = realizar_matricula(criar_aluno_valido(), self.plano, self.hoje, 'pix')
        with mock.patch('financeiro.servicos.renovar_matricula') as r:
            r.return_value = {'renovada': False}
            renovar_automaticas(self.hoje)
        chamadas = [c.args[0].pk for c in r.call_args_list]
        self.assertIn(self.matricula.pk, chamadas)
        self.assertNotIn(longe.pk, chamadas)

class TarefaT16TrancamentoTests(TestCase):
    """Trancar a matrícula: suspende cobranças, prorroga vigência, respeita limite anual."""

    def setUp(self):
        RegraFinanceira.obter()
        self.hoje = timezone.localdate()
        self.plano = Plano.objects.create(
            nome='Mensal T16', periodicidade='mensal', valor=Decimal('100.00'), dia_vencimento=10,
        )
        self.aluno = criar_aluno_valido()
        self.matricula = Matricula.objects.create(
            aluno=self.aluno, plano=self.plano,
            data_inicio=self.hoje - timedelta(days=30), forma_pagamento='pix',
        )
        self._n = count(1)

    def cobranca_em(self, dias_a_partir_de_hoje):
        return Cobranca.objects.create(
            matricula=self.matricula, tipo='mensalidade', valor=Decimal('100.00'),
            vencimento=self.hoje + timedelta(days=dias_a_partir_de_hoje),
            competencia=f'2090-{next(self._n):02d}',
        )

    def trancar(self, ini=1, fim=31, base=None, **kw):
        from .servicos import trancar_matricula
        base = base or self.hoje
        return trancar_matricula(
            self.matricula,
            base + timedelta(days=ini),
            base + timedelta(days=fim),
            hoje=base,
            **kw,
        )

    # 1. registro com início e retorno
    def test_registra_inicio_e_retorno(self):
        t = self.trancar(1, 31, motivo='Viagem')['trancamento']
        self.assertEqual(t.dias, 30)
        self.assertEqual(t.motivo, 'Viagem')
        self.assertEqual(self.matricula.trancamentos.count(), 1)

    def test_retorno_deve_ser_depois_do_inicio(self):
        with self.assertRaises(ValidationError):
            self.trancar(10, 10)
        self.assertEqual(Trancamento.objects.count(), 0)

    # 2. cobranças do período suspensas
    def test_cobrancas_do_periodo_ficam_suspensas(self):
        dentro = self.cobranca_em(10)
        fora = self.cobranca_em(90)
        r = self.trancar(1, 31)
        dentro.refresh_from_db()
        fora.refresh_from_db()
        self.assertTrue(dentro.suspensa)
        self.assertEqual(dentro.trancamento, r['trancamento'])
        self.assertFalse(fora.suspensa)
        self.assertEqual(r['cobrancas_suspensas'], 1)

    def test_cobranca_paga_nao_e_suspensa(self):
        paga = self.cobranca_em(10)
        paga.paga = True
        paga.save()
        self.trancar(1, 31)
        paga.refresh_from_db()
        self.assertFalse(paga.suspensa)

    # 3. vigência prorrogada
    def test_vigencia_prorrogada_pelos_dias_trancados(self):
        from .servicos import fim_vigencia
        antes = fim_vigencia(self.matricula)
        self.trancar(1, 21)
        self.assertEqual(fim_vigencia(self.matricula), antes + timedelta(days=20))

    # 4. acesso bloqueado
    def test_acesso_bloqueado_durante_o_trancamento(self):
        self.trancar(0, 10)
        r = avaliar_situacao_financeira_aluno(self.aluno)
        self.assertEqual(r['status'], 'bloqueado')
        self.assertIn('TRANCADA', r['motivo'])

    # 5. limite anual
    def test_excesso_do_limite_e_recusado_com_motivo(self):
        regras = RegraFinanceira.obter()
        regras.limite_dias_trancamento_ano = 30
        regras.save()
        with self.assertRaises(ValidationError) as ctx:
            self.trancar(1, 41)
        self.assertIn('Limite de 30 dias', ctx.exception.messages[0])
        self.assertEqual(Trancamento.objects.count(), 0)

    def test_limite_soma_trancamentos_anteriores_no_mesmo_ano(self):
        regras = RegraFinanceira.obter()
        regras.limite_dias_trancamento_ano = 40
        regras.save()
        base = date(self.hoje.year + 1, 1, 1)
        self.trancar(1, 31, base=base)    # 30 dias
        with self.assertRaises(ValidationError):
            self.trancar(40, 55, base=base)  # +15 > 40
        self.assertEqual(Trancamento.objects.count(), 1)

    def test_nao_aceita_periodos_sobrepostos(self):
        self.trancar(1, 21)
        with self.assertRaises(ValidationError):
            self.trancar(10, 30)

    # 6. trancada no período e volta a ativa
    def test_trancada_no_periodo_e_ativa_no_retorno(self):
        self.trancar(0, 10)
        self.assertEqual(
            calcular_situacao(self.matricula, hoje=self.hoje + timedelta(days=9)),
            SituacaoMatricula.TRANCADA,
        )
        self.assertEqual(
            calcular_situacao(self.matricula, hoje=self.hoje + timedelta(days=10)),
            SituacaoMatricula.ATIVA,
        )

    def test_cobranca_suspensa_nao_gera_atraso(self):
        c = self.cobranca_em(5)
        self.trancar(1, 31)
        depois = self.hoje + timedelta(days=60)
        self.assertEqual(calcular_situacao(self.matricula, hoje=depois), SituacaoMatricula.ATIVA)

    # 7. histórico
    def test_historico_guarda_quem_registrou(self):
        usuario = criar_usuario('rec_t16', Perfil.RECEPCAO)
        self.trancar(1, 11, usuario=usuario, motivo='Lesão')
        t = self.matricula.trancamentos.get()
        self.assertEqual(t.registrado_por, usuario)
        self.assertEqual(t.registrado_por_nome, 'rec_t16')

    def test_matricula_cancelada_nao_tranca(self):
        Cancelamento.objects.create(matricula=self.matricula, data=self.hoje)
        with self.assertRaises(ValidationError):
            self.trancar(1, 11)


class TarefaT16TelaTests(TestCase):
    def setUp(self):
        RegraFinanceira.obter()
        self.hoje = timezone.localdate()
        self.recepcao = criar_usuario('rec_tela_t16', 'recepcao')
        self.client = Client()
        self.client.force_login(self.recepcao)
        plano = Plano.objects.create(
            nome='Mensal',
            periodicidade='mensal',
            valor=Decimal('100.00'),
            dia_vencimento=10,
        )
        self.matricula = Matricula.objects.create(
            aluno=criar_aluno_valido(),
            plano=plano,
            data_inicio=self.hoje - timedelta(days=10),
            forma_pagamento='pix',
        )
        self.url = reverse(
            'trancar_matricula',
            args=[self.matricula.pk],
        )

    def dados(self, ini=1, fim=11):
        return {
            'data_inicio': (
                self.hoje + timedelta(days=ini)
            ).isoformat(),
            'data_fim': (
                self.hoje + timedelta(days=fim)
            ).isoformat(),
            'motivo': 'Viagem',
        }

    def test_post_valido_redireciona_para_o_historico(self):
        resposta = self.client.post(self.url, self.dados())

        self.assertRedirects(
            resposta,
            reverse(
                'historico_trancamentos',
                args=[self.matricula.pk],
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.matricula.trancamentos.count(),
            1,
        )

    def test_excesso_do_limite_mostra_o_motivo_na_tela(self):
        regras = RegraFinanceira.obter()
        regras.limite_dias_trancamento_ano = 5
        regras.save()

        resposta = self.client.post(
            self.url,
            self.dados(1, 31),
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Limite de 5 dias')
        self.assertEqual(Trancamento.objects.count(), 0)

    def test_historico_lista_o_trancamento(self):
        self.client.post(self.url, self.dados())

        resposta = self.client.get(
            reverse(
                'historico_trancamentos',
                args=[self.matricula.pk],
            )
        )

        self.assertContains(resposta, 'Viagem')

    def test_so_recepcao_acessa(self):
        outro = Client()
        outro.force_login(
            criar_usuario('prof_t16', 'professor')
        )

        self.assertEqual(outro.get(self.url).status_code, 302)
        self.assertEqual(Client().get(self.url).status_code, 302)