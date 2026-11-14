from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno
from avaliacoes.models import AvaliacaoFisica
from recepcao.models import Frequencia

from .servicos import frequencia_no_periodo, normalizar_periodo


class BaseRetencaoTest(TestCase):
    def setUp(self):
        self.professor = self.criar_usuario('prof', Perfil.PROFESSOR)
        self.aluna = self.criar_aluno('ana', '12345678901', 'Ana Souza')
        self.outra = self.criar_aluno('bia', '12345678902', 'Bia Lima')
        self.hoje = timezone.localdate()
        self.url = reverse('numeros_da_academia')

    def criar_usuario(self, username, tipo):
        u = User.objects.create_user(username=username, password='senha12345')
        Perfil.objects.create(usuario=u, tipo=tipo)
        return u

    def criar_aluno(self, username, cpf, nome):
        u = User.objects.create_user(username=username, password='senha12345')
        perfil = Perfil.objects.create(usuario=u, tipo=Perfil.ALUNO)
        return Aluno.objects.create(
            perfil=perfil, nome=nome, cpf=cpf, data_nascimento='2000-01-01',
            endereco='Rua A, 1', telefone=f'8199999{cpf[-4:]}',
            email=f'{username}@exemplo.com',
            contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
        )

    def entrada(self, aluno, dias_atras=0, liberado=True):
        """Cria uma entrada. `data_hora` é auto_now_add, então ajustamos depois."""
        f = Frequencia.objects.create(aluno=aluno, liberado=liberado)
        Frequencia.objects.filter(pk=f.pk).update(
            data_hora=timezone.now() - timedelta(days=dias_atras, minutes=1)
        )
        return f

    def avaliacao(self, aluno=None, dias_atras=0, peso='70.00', **extra):
        return AvaliacaoFisica.objects.create(
            aluno=aluno or self.aluna, professor=self.professor,
            data_avaliacao=self.hoje - timedelta(days=dias_atras),
            peso_kg=Decimal(peso), altura_cm=Decimal('170.0'), **extra,
        )

    def entrar_como(self, username):
        self.client.login(username=username, password='senha12345')


class FrequenciaServicoTests(BaseRetencaoTest):
    def test_conta_so_acessos_do_periodo(self):
        self.entrada(self.aluna, dias_atras=1)
        self.entrada(self.aluna, dias_atras=20)
        self.entrada(self.aluna, dias_atras=60)
        self.assertEqual(frequencia_no_periodo(self.aluna, '7')['total'], 1)
        self.assertEqual(frequencia_no_periodo(self.aluna, '30')['total'], 2)
        self.assertEqual(frequencia_no_periodo(self.aluna, '90')['total'], 3)

    def test_entrada_bloqueada_nao_conta_como_acesso(self):
        self.entrada(self.aluna, dias_atras=1)
        self.entrada(self.aluna, dias_atras=2, liberado=False)
        self.assertEqual(frequencia_no_periodo(self.aluna, '30')['total'], 1)

    def test_nao_conta_acessos_de_outra_aluna(self):
        self.entrada(self.outra, dias_atras=1)
        self.assertEqual(frequencia_no_periodo(self.aluna, '30')['total'], 0)

    def test_media_semanal(self):
        for dias in (1, 2, 3, 4):
            self.entrada(self.aluna, dias_atras=dias)
        # 4 acessos em 7 dias = 4,0/semana; em 30 dias seria 0,9
        self.assertEqual(frequencia_no_periodo(self.aluna, '7')['media_semanal'], Decimal('4.0'))
        self.assertEqual(frequencia_no_periodo(self.aluna, '30')['media_semanal'], Decimal('0.9'))

    def test_periodo_invalido_cai_no_padrao(self):
        self.assertEqual(normalizar_periodo('abc'), '30')
        self.assertEqual(normalizar_periodo(None), '30')
        self.assertEqual(normalizar_periodo('90'), '90')


class TelaTests(BaseRetencaoTest):
    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn('entrar', resposta.url)

    def test_professor_nao_acessa(self):
        self.entrar_como('prof')
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, reverse('painel'), fetch_redirect_response=False)

    def test_aluna_ve_frequencia_do_periodo(self):
        self.entrada(self.aluna, dias_atras=1)
        self.entrada(self.aluna, dias_atras=2)
        self.entrada(self.aluna, dias_atras=100)
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'periodo': '30'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['frequencia']['total'], 2)
        resposta = self.client.get(self.url, {'periodo': '365'})
        self.assertEqual(resposta.context['frequencia']['total'], 3)

    def test_periodo_invalido_na_url_nao_quebra(self):
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'periodo': 'xx'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['periodo'], '30')

    def test_aluna_so_ve_dados_proprios(self):
        self.entrada(self.outra, dias_atras=1)
        self.avaliacao(self.outra, peso='97.35')
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.context['frequencia']['total'], 0)
        self.assertEqual(list(resposta.context['avaliacoes']), [])
        self.assertNotContains(resposta, '97,35')

    def test_serie_historica_completa_em_ordem_cronologica(self):
        a1 = self.avaliacao(dias_atras=60, peso='72.00')
        a2 = self.avaliacao(dias_atras=30, peso='70.00')
        a3 = self.avaliacao(dias_atras=0, peso='68.00')
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        self.assertEqual([a.pk for a in resposta.context['avaliacoes']], [a1.pk, a2.pk, a3.pk])

    def test_serie_inclui_avaliacao_corrigida(self):
        original = self.avaliacao(dias_atras=10, peso='70.00')
        correcao = self.avaliacao(
            dias_atras=10, peso='71.00', corrige=original, motivo_correcao='Erro de digitação',
        )
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        pks = [a.pk for a in resposta.context['avaliacoes']]
        self.assertIn(original.pk, pks)
        self.assertIn(correcao.pk, pks)
        self.assertContains(resposta, 'Substituída')
        self.assertContains(resposta, 'Correção')

    def test_comparacao_escolhida_mostra_diferenca_de_cada_medida(self):
        a1 = self.avaliacao(dias_atras=30, peso='72.00', cintura_cm=Decimal('80.0'))
        a2 = self.avaliacao(dias_atras=0, peso='70.00', cintura_cm=Decimal('77.0'))
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'a': a2.pk, 'b': a1.pk})  # ordem trocada de propósito
        linhas = {l.rotulo: l for l in resposta.context['linhas']}
        self.assertEqual(linhas['Peso'].diferenca, Decimal('-2.00'))
        self.assertEqual(linhas['Cintura'].diferenca, Decimal('-3.0'))
        self.assertEqual(resposta.context['anterior'].pk, a1.pk)
        self.assertEqual(resposta.context['posterior'].pk, a2.pk)

    def test_sem_escolha_sugere_as_duas_vigentes_mais_recentes(self):
        self.avaliacao(dias_atras=60)
        a2 = self.avaliacao(dias_atras=30)
        a3 = self.avaliacao(dias_atras=0)
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.context['anterior'].pk, a2.pk)
        self.assertEqual(resposta.context['posterior'].pk, a3.pk)

    def test_comparar_com_avaliacao_de_outra_aluna_e_recusado(self):
        minha = self.avaliacao()
        alheia = self.avaliacao(self.outra)
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'a': minha.pk, 'b': alheia.pk})
        self.assertEqual(resposta.context['linhas'], [])
        self.assertContains(resposta, 'Escolha duas avaliações da lista.')

    def test_comparar_a_mesma_avaliacao_e_recusado(self):
        a = self.avaliacao()
        self.avaliacao(dias_atras=5)
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'a': a.pk, 'b': a.pk})
        self.assertEqual(resposta.context['linhas'], [])
        self.assertContains(resposta, 'Escolha duas avaliações diferentes')

    def test_ids_invalidos_nao_quebram(self):
        self.avaliacao()
        self.entrar_como('ana')
        resposta = self.client.get(self.url, {'a': 'x', 'b': ''})
        self.assertEqual(resposta.status_code, 200)

    def test_aluna_sem_nenhuma_avaliacao_ve_a_tela_sem_erro(self):
        self.entrada(self.aluna, dias_atras=1)
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['frequencia']['total'], 1)
        self.assertContains(resposta, 'ainda não tem avaliação física')
        self.assertContains(resposta, 'Ana')
        self.assertNotContains(resposta, '…')
        self.assertNotContains(resposta, 'Compare duas avaliações')

    def test_aluna_com_uma_avaliacao_ainda_nao_compara(self):
        self.avaliacao()
        self.entrar_como('ana')
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Com mais uma avaliação')
        self.assertEqual(resposta.context['linhas'], [])

    def test_painel_da_aluna_tem_o_link_para_a_tela(self):
        self.entrar_como('ana')
        resposta = self.client.get(reverse('painel_aluno'))
        self.assertContains(resposta, self.url)