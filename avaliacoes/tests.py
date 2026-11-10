from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno
from .models import AvaliacaoFisica, RegistroImutavelError, TesteFisico
from .servicos import comparar_avaliacoes


class BaseAvaliacaoTest(TestCase):
    def setUp(self):
        self.professor = self.criar_usuario('prof', Perfil.PROFESSOR)
        self.aluno = self.criar_aluno('ana', '12345678901', 'Ana Souza')
        self.outro = self.criar_aluno('bia', '12345678902', 'Bia Lima')
        self.hoje = timezone.localdate()

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

    def avaliacao(self, aluno=None, dias_atras=0, peso='70.00', altura='170.0', **extra):
        return AvaliacaoFisica.objects.create(
            aluno=aluno or self.aluno, professor=self.professor,
            data_avaliacao=self.hoje - timedelta(days=dias_atras),
            peso_kg=Decimal(peso), altura_cm=Decimal(altura), **extra,
        )

    def dados(self, **extra):
        d = {
            'data_avaliacao': self.hoje.isoformat(),
            'peso_kg': '70.00', 'altura_cm': '170.0', 'percentual_gordura': '25.0',
            'cintura_cm': '80.0', 'observacoes': '',
            'testes-TOTAL_FORMS': '2', 'testes-INITIAL_FORMS': '0',
            'testes-MIN_NUM_FORMS': '0', 'testes-MAX_NUM_FORMS': '1000',
            'testes-0-nome': 'Flexões', 'testes-0-resultado': '15', 'testes-0-unidade': 'rep',
            'testes-1-nome': '', 'testes-1-resultado': '', 'testes-1-unidade': '',
        }
        d.update(extra)
        return d


class ModeloTests(BaseAvaliacaoTest):
    def test_imc_e_calculado_do_peso_e_da_altura(self):
        # 70 / 1,70² = 24,22
        self.assertEqual(self.avaliacao().imc, Decimal('24.22'))

    def test_imc_nao_e_coluna_do_banco(self):
        nomes = [f.name for f in AvaliacaoFisica._meta.get_fields()]
        self.assertNotIn('imc', nomes)

    def test_save_de_registro_existente_e_bloqueado(self):
        av = self.avaliacao()
        av.peso_kg = Decimal('60')
        with self.assertRaises(RegistroImutavelError):
            av.save()
        av.refresh_from_db()
        self.assertEqual(av.peso_kg, Decimal('70.00'))

    def test_update_e_delete_em_massa_sao_bloqueados(self):
        av = self.avaliacao()
        with self.assertRaises(RegistroImutavelError):
            AvaliacaoFisica.objects.filter(pk=av.pk).update(peso_kg=Decimal('1'))
        with self.assertRaises(RegistroImutavelError):
            AvaliacaoFisica.objects.all().delete()
        with self.assertRaises(RegistroImutavelError):
            av.delete()

    def test_teste_fisico_tambem_e_imutavel(self):
        t = TesteFisico.objects.create(avaliacao=self.avaliacao(), nome='Flexões', resultado=Decimal('10'))
        t.resultado = Decimal('99')
        with self.assertRaises(RegistroImutavelError):
            t.save()
        with self.assertRaises(RegistroImutavelError):
            t.delete()

    def test_uma_avaliacao_so_e_corrigida_uma_vez(self):
        original = self.avaliacao()
        self.avaliacao(corrige=original, motivo_correcao='erro')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.avaliacao(corrige=original, motivo_correcao='outro erro')

    def test_vigente_e_substituida_por(self):
        original = self.avaliacao()
        self.assertTrue(original.vigente)
        correcao = self.avaliacao(corrige=original, motivo_correcao='erro')
        original = AvaliacaoFisica.objects.get(pk=original.pk)
        self.assertFalse(original.vigente)
        self.assertEqual(original.substituida_por, correcao)


class RegistroViewTests(BaseAvaliacaoTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.professor)

    def test_registra_avaliacao_com_testes_vinculada_ao_aluno(self):
        r = self.client.post(reverse('registrar_avaliacao', args=[self.aluno.pk]), self.dados())
        self.assertEqual(r.status_code, 302)
        av = AvaliacaoFisica.objects.get()
        self.assertEqual(av.aluno, self.aluno)
        self.assertEqual(av.professor, self.professor)
        self.assertEqual(av.data_avaliacao, self.hoje)
        self.assertEqual(av.testes.get().nome, 'Flexões')

    def test_imc_digitado_e_ignorado(self):
        self.client.post(reverse('registrar_avaliacao', args=[self.aluno.pk]), self.dados(imc='99'))
        self.assertEqual(AvaliacaoFisica.objects.get().imc, Decimal('24.22'))

    def test_nova_avaliacao_nao_sobrescreve_a_anterior(self):
        url = reverse('registrar_avaliacao', args=[self.aluno.pk])
        self.client.post(url, self.dados(peso_kg='72.00', data_avaliacao=(self.hoje - timedelta(days=30)).isoformat()))
        self.client.post(url, self.dados(peso_kg='70.00'))
        self.assertEqual(AvaliacaoFisica.objects.filter(aluno=self.aluno).count(), 2)
        self.assertEqual(
            sorted(AvaliacaoFisica.objects.values_list('peso_kg', flat=True)),
            [Decimal('70.00'), Decimal('72.00')],
        )

    def test_rejeita_data_futura_peso_ausente_e_teste_repetido(self):
        url = reverse('registrar_avaliacao', args=[self.aluno.pk])
        self.client.post(url, self.dados(data_avaliacao=(self.hoje + timedelta(days=1)).isoformat()))
        self.client.post(url, self.dados(peso_kg=''))
        self.client.post(url, self.dados(**{
            'testes-TOTAL_FORMS': '2', 'testes-1-nome': 'flexões', 'testes-1-resultado': '3',
        }))
        self.assertEqual(AvaliacaoFisica.objects.count(), 0)

    def test_aluno_nao_registra(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.post(reverse('registrar_avaliacao', args=[self.aluno.pk]), self.dados())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AvaliacaoFisica.objects.count(), 0)


class CorrecaoTests(BaseAvaliacaoTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.professor)
        self.original = self.avaliacao(peso='75.00')
        TesteFisico.objects.create(avaliacao=self.original, nome='Flexões', resultado=Decimal('10'), unidade='rep')
        self.url = reverse('corrigir_avaliacao', args=[self.original.pk])

    def test_correcao_cria_registro_novo_e_preserva_o_original(self):
        r = self.client.post(self.url, self.dados(peso_kg='57.00', motivo_correcao='Digitei 75 em vez de 57'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AvaliacaoFisica.objects.count(), 2)
        self.original.refresh_from_db()
        self.assertEqual(self.original.peso_kg, Decimal('75.00'))
        correcao = AvaliacaoFisica.objects.get(corrige=self.original)
        self.assertEqual(correcao.peso_kg, Decimal('57.00'))
        self.assertEqual(correcao.motivo_correcao, 'Digitei 75 em vez de 57')
        self.assertEqual(self.original.testes.count(), 1)

    def test_motivo_e_obrigatorio(self):
        self.client.post(self.url, self.dados(motivo_correcao='  '))
        self.assertEqual(AvaliacaoFisica.objects.count(), 1)

    def test_nao_corrige_avaliacao_ja_corrigida(self):
        self.client.post(self.url, self.dados(motivo_correcao='erro'))
        self.client.post(self.url, self.dados(motivo_correcao='erro 2'))
        self.assertEqual(AvaliacaoFisica.objects.count(), 2)

    def test_formulario_vem_preenchido_com_valores_e_testes_originais(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'value="75.00"')
        self.assertContains(r, 'value="Flexões"')


class VisaoDoAlunoTests(BaseAvaliacaoTest):
    def setUp(self):
        super().setUp()
        self.a1 = self.avaliacao(dias_atras=60, peso='80.00')
        self.a2 = self.avaliacao(dias_atras=30, peso='76.00')
        self.a3 = self.avaliacao(dias_atras=0, peso='73.00')
        self.alheia = self.avaliacao(aluno=self.outro, peso='55.00')

    def test_aluno_ve_serie_completa_so_dele(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_evolucao'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['avaliacoes']), 3)
        self.assertNotIn(self.alheia, r.context['avaliacoes'])

    def test_serie_inclui_avaliacoes_corrigidas(self):
        self.avaliacao(dias_atras=0, peso='72.00', corrige=self.a3, motivo_correcao='erro')
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_evolucao'))
        self.assertEqual(len(r.context['avaliacoes']), 4)

    def test_professor_nao_acessa_rota_do_aluno_e_vice_versa(self):
        self.client.force_login(self.professor)
        self.assertEqual(self.client.get(reverse('minha_evolucao')).status_code, 302)
        self.client.force_login(self.aluno.perfil.usuario)
        self.assertEqual(self.client.get(reverse('avaliacoes_aluno', args=[self.aluno.pk])).status_code, 302)

    def test_comparacao_mostra_diferenca_de_cada_medida(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_comparacao'), {'a': self.a1.pk, 'b': self.a3.pk})
        linhas = {l.rotulo: l for l in r.context['linhas']}
        self.assertEqual(linhas['Peso'].diferenca, Decimal('-7.00'))
        self.assertEqual(linhas['Peso'].diferenca_texto, '-7,00')

    def test_comparacao_padrao_usa_as_duas_ultimas(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_comparacao'))
        self.assertEqual(r.context['anterior'], self.a2)
        self.assertEqual(r.context['posterior'], self.a3)

    def test_aluno_nao_compara_avaliacao_de_outro(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_comparacao'), {'a': self.a1.pk, 'b': self.alheia.pk})
        self.assertEqual(r.context['linhas'], [])

    def test_comparar_a_mesma_avaliacao_e_recusado(self):
        self.client.force_login(self.aluno.perfil.usuario)
        r = self.client.get(reverse('minha_comparacao'), {'a': self.a1.pk, 'b': self.a1.pk})
        self.assertEqual(r.context['linhas'], [])


class ComparacaoServicoTests(BaseAvaliacaoTest):
    def test_ordem_da_escolha_nao_importa(self):
        antiga = self.avaliacao(dias_atras=10, peso='80.00')
        recente = self.avaliacao(dias_atras=0, peso='78.00')
        ant, pos, linhas = comparar_avaliacoes(recente, antiga)
        self.assertEqual((ant, pos), (antiga, recente))
        self.assertEqual(next(l for l in linhas if l.rotulo == 'Peso').diferenca, Decimal('-2.00'))

    def test_medida_ausente_de_um_lado_fica_sem_diferenca(self):
        a = self.avaliacao(dias_atras=10)
        b = self.avaliacao(dias_atras=0, cintura_cm=Decimal('80.0'))
        _, _, linhas = comparar_avaliacoes(a, b)
        cintura = next(l for l in linhas if l.rotulo == 'Cintura')
        self.assertIsNone(cintura.diferenca)
        self.assertEqual(cintura.diferenca_texto, '—')

    def test_testes_sao_casados_pelo_nome_e_unidades_diferentes_nao_somam(self):
        a = self.avaliacao(dias_atras=10)
        b = self.avaliacao(dias_atras=0)
        TesteFisico.objects.create(avaliacao=a, nome='Flexões', resultado=Decimal('10'), unidade='rep')
        TesteFisico.objects.create(avaliacao=b, nome='flexões ', resultado=Decimal('15'), unidade='rep')
        TesteFisico.objects.create(avaliacao=a, nome='Corrida', resultado=Decimal('12'), unidade='min')
        TesteFisico.objects.create(avaliacao=b, nome='Corrida', resultado=Decimal('700'), unidade='s')
        _, _, linhas = comparar_avaliacoes(a, b)
        testes = {l.rotulo.strip().casefold(): l for l in linhas if l.eh_teste}
        self.assertEqual(testes['flexões'].diferenca, Decimal('5'))
        self.assertIsNone(testes['corrida'].diferenca)
        self.assertTrue(testes['corrida'].aviso)