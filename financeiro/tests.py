from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from datetime import date

from accounts.models import Perfil
from alunos.models import Aluno
from .models import RegraFinanceira, HistoricoRegraFinanceira, Plano, Matricula, Cobranca
from .servicos import realizar_matricula


def criar_usuario(username, tipo):
    usuario = User.objects.create_user(username=username, password='senha12345')
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


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
        self.aluno = Aluno.objects.create(nome="Aluno Teste")
        if hasattr(self.aluno, 'tem_anamnese'):
            self.aluno.tem_anamnese = True
        if hasattr(self.aluno, 'tem_autorizacao'):
            self.aluno.tem_autorizacao = True
        self.aluno.save()

        self.plano = Plano.objects.create(
            nome="Trimestral",
            periodicidade="trimestral",
            valor=Decimal('150.00'),
            taxa_adesao=Decimal('40.00'),
            dia_vencimento=10
        )

    def test_realizar_matricula_gera_cobrancas_e_idempotencia(self):
        data_inicio = date(2027, 2, 1)
        
        matricula = realizar_matricula(self.aluno, self.plano, data_inicio, 'pix')
        
        # 1 taxa de adesão + 3 mensalidades (trimestral) = 4 cobranças
        total_cobrancas = Cobranca.objects.filter(matricula=matricula).count()
        self.assertEqual(total_cobrancas, 4)
        
        # Valida idempotência: rodar de novo não pode duplicar as cobranças de mensalidade
        realizar_matricula(self.aluno, self.plano, data_inicio, 'pix')
        total_cobrancas_reaplicado = Cobranca.objects.filter(matricula=matricula).count()
        self.assertEqual(total_cobrancas, total_cobrancas_reaplicado)

    def test_bloqueio_aluno_sem_liberacao(self):
        if hasattr(self.aluno, 'tem_anamnese'):
            self.aluno.tem_anamnese = False
            self.aluno.save()
            
        with self.assertRaises(ValidationError):
            realizar_matricula(self.aluno, self.plano, date(2027, 2, 1), 'pix')