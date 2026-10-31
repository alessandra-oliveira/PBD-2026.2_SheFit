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
    Trancamento, Cancelamento, SituacaoMatricula, Pagamento, Estorno,
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
        self.assertEqual(self.situacao(self.hoje + timedelta(days=10)), SituacaoMatricula.TRANCADA)
        self.assertEqual(self.situacao(self.hoje + timedelta(days=11)), SituacaoMatricula.BLOQUEADA)

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