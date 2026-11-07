from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta
from itertools import count

from accounts.models import Perfil
from alunos.forms import MatriculaForm as MatriculaFormDoApp
from alunos.models import Aluno, Anamnese
from .forms import MatriculaForm
from .models import (
    RegraFinanceira, HistoricoRegraFinanceira, Plano, Matricula, Cobranca,
    Trancamento, Cancelamento, SituacaoMatricula,
)
from .servicos import (
    realizar_matricula, gerar_cobrancas, calcular_situacao, avaliar_situacao_financeira_aluno,
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