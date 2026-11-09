from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno, Anamnese
from .models import ExercicioTreino, FichaTreino


class FichasTreinoTests(TestCase):
    def setUp(self):
        self.professor = User.objects.create_user(username='prof', password='senha12345')
        Perfil.objects.create(usuario=self.professor, tipo=Perfil.PROFESSOR)
        self.aluno = self.criar_aluno('aluna', '12345678901', 'Ana Souza')
        self.outro_aluno = self.criar_aluno('outra', '12345678902', 'Bia Lima')
        self.client.force_login(self.professor)

    def criar_aluno(self, username, cpf, nome):
        usuario = User.objects.create_user(username=username, password='senha12345')
        perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.ALUNO)
        return Aluno.objects.create(
            perfil=perfil,
            nome=nome,
            cpf=cpf,
            data_nascimento='2000-01-01',
            endereco='Rua A, 1',
            telefone=f'8199999{cpf[-4:]}',
            email=f'{username}@exemplo.com',
            contato_emergencia_nome='Contato',
            contato_emergencia_telefone='81988887777',
        )

    def dados_ficha(self, aluno=None, data_revisao=None):
        return {
            'aluno': str((aluno or self.aluno).pk),
            'data_revisao': (data_revisao or timezone.localdate() + timedelta(days=30)).isoformat(),
            'exercicios-TOTAL_FORMS': '2',
            'exercicios-INITIAL_FORMS': '0',
            'exercicios-MIN_NUM_FORMS': '0',
            'exercicios-MAX_NUM_FORMS': '1000',
            'exercicios-0-nome': 'Agachamento',
            'exercicios-0-series': '3',
            'exercicios-0-repeticoes': '12',
            'exercicios-0-carga_sugerida': '20.50',
            'exercicios-0-observacoes': 'Manter postura',
            'exercicios-1-nome': '',
            'exercicios-1-series': '',
            'exercicios-1-repeticoes': '',
            'exercicios-1-carga_sugerida': '',
            'exercicios-1-observacoes': '',
        }

    def test_cria_ficha_e_persiste_varios_exercicios(self):
        dados = self.dados_ficha()
        dados.update({
            'exercicios-TOTAL_FORMS': '3',
            'exercicios-1-nome': 'Remada',
            'exercicios-1-series': '4',
            'exercicios-1-repeticoes': '10',
            'exercicios-1-carga_sugerida': '',
            'exercicios-1-observacoes': '',
            'exercicios-2-nome': '',
            'exercicios-2-series': '',
            'exercicios-2-repeticoes': '',
            'exercicios-2-carga_sugerida': '',
            'exercicios-2-observacoes': '',
        })

        resposta = self.client.post(reverse('criar_ficha'), dados)

        self.assertEqual(resposta.status_code, 302)
        ficha = FichaTreino.objects.get(aluno=self.aluno, ativa=True)
        self.assertEqual(ficha.professor, self.professor)
        self.assertEqual(ficha.data_revisao, date.fromisoformat(dados['data_revisao']))
        self.assertIsNotNone(ficha.criada_em)
        exercicios = list(ficha.exercicios.order_by('nome'))
        self.assertEqual([item.nome for item in exercicios], ['Agachamento', 'Remada'])
        agachamento = next(item for item in exercicios if item.nome == 'Agachamento')
        self.assertEqual(agachamento.series, 3)
        self.assertEqual(agachamento.repeticoes, 12)
        self.assertEqual(agachamento.carga_sugerida, Decimal('20.50'))
        self.assertEqual(agachamento.observacoes, 'Manter postura')
        remada = next(item for item in exercicios if item.nome == 'Remada')
        self.assertIsNone(remada.carga_sugerida)

    def test_substitui_ficha_ativa_sem_alterar_exercicios_do_historico(self):
        anterior = FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate(),
        )
        ExercicioTreino.objects.create(
            ficha=anterior,
            nome='Supino',
            series=3,
            repeticoes=8,
            carga_sugerida=Decimal('30.00'),
            observacoes='Histórico preservado',
        )

        resposta = self.client.post(reverse('criar_ficha'), self.dados_ficha())

        self.assertEqual(resposta.status_code, 302)
        anterior.refresh_from_db()
        nova = FichaTreino.objects.get(aluno=self.aluno, ativa=True)
        self.assertFalse(anterior.ativa)
        self.assertIsNotNone(anterior.encerrada_em)
        self.assertEqual(anterior.exercicios.count(), 1)
        self.assertEqual(anterior.exercicios.get().observacoes, 'Histórico preservado')
        self.assertNotEqual(anterior.pk, nova.pk)

    @patch('treinos.views.ExercicioTreinoFormSet.save', side_effect=RuntimeError('falha ao salvar exercícios'))
    def test_erro_ao_salvar_exercicios_reverte_a_substituicao(self, _salvar_exercicios):
        anterior = FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate(),
        )

        with self.assertRaises(RuntimeError):
            self.client.post(reverse('criar_ficha'), self.dados_ficha())

        anterior.refresh_from_db()
        self.assertTrue(anterior.ativa)
        self.assertIsNone(anterior.encerrada_em)
        self.assertEqual(FichaTreino.objects.filter(aluno=self.aluno).count(), 1)

    def test_banco_impede_duas_fichas_ativas_para_o_mesmo_aluno(self):
        FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate(),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FichaTreino.objects.create(
                    aluno=self.aluno,
                    professor=self.professor,
                    data_revisao=timezone.localdate(),
                )

    def test_anamnese_e_exibida_na_tela_de_montagem(self):
        Anamnese.objects.create(
            aluno=self.aluno,
            restricoes_medicas='Evitar impacto',
            historico_lesoes='Lesão no joelho',
            condicoes_cronicas='Asma',
            autorizacao_atividade_fisica=True,
        )

        resposta = self.client.get(reverse('criar_ficha'), {'aluno': self.aluno.pk})

        self.assertContains(resposta, 'Evitar impacto')
        self.assertContains(resposta, 'Lesão no joelho')
        self.assertContains(resposta, 'Asma')
        self.assertContains(resposta, 'Confirmada')

    def test_painel_lista_apenas_fichas_ativas_com_revisao_vencida(self):
        vencida = FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate() - timedelta(days=1),
        )
        FichaTreino.objects.create(
            aluno=self.outro_aluno,
            professor=self.professor,
            data_revisao=timezone.localdate() + timedelta(days=1),
        )
        FichaTreino.objects.create(
            aluno=self.outro_aluno,
            professor=self.professor,
            data_revisao=timezone.localdate() - timedelta(days=2),
            ativa=False,
            encerrada_em=timezone.now(),
        )

        resposta = self.client.get(reverse('painel_professor'))

        self.assertContains(resposta, 'Ana Souza')
        self.assertContains(resposta, vencida.data_revisao.strftime('%d/%m/%Y'))
        self.assertNotContains(resposta, 'Bia Lima')

    def test_professor_pode_criar_ficha_para_qualquer_aluno(self):
        resposta = self.client.post(
            reverse('criar_ficha'),
            self.dados_ficha(aluno=self.outro_aluno),
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(FichaTreino.objects.filter(aluno=self.outro_aluno, ativa=True).exists())

    def test_aluno_visualiza_apenas_sua_ficha_ativa_no_painel(self):
        antiga = FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate(),
            ativa=False,
            encerrada_em=timezone.now(),
        )
        ExercicioTreino.objects.create(ficha=antiga, nome='Exercício do histórico')
        propria = FichaTreino.objects.create(
            aluno=self.aluno,
            professor=self.professor,
            data_revisao=timezone.localdate() + timedelta(days=10),
        )
        ExercicioTreino.objects.create(ficha=propria, nome='Agachamento')
        alheia = FichaTreino.objects.create(
            aluno=self.outro_aluno,
            professor=self.professor,
            data_revisao=timezone.localdate() + timedelta(days=10),
        )
        ExercicioTreino.objects.create(ficha=alheia, nome='Exercício confidencial')

        self.client.force_login(self.aluno.perfil.usuario)
        resposta = self.client.get(reverse('painel_aluno'))

        self.assertContains(resposta, 'Agachamento')
        self.assertNotContains(resposta, 'Exercício confidencial')
        self.assertNotContains(resposta, 'Exercício do histórico')

        resposta_ficha = self.client.get(reverse('ficha_ativa_aluno'))
        self.assertContains(resposta_ficha, 'Agachamento')
        self.assertNotContains(resposta_ficha, 'Exercício confidencial')
        self.assertNotContains(resposta_ficha, 'Exercício do histórico')

    def test_aluno_nao_pode_criar_ou_consultar_ficha_de_professor(self):
        self.client.force_login(self.aluno.perfil.usuario)

        resposta_criacao = self.client.post(
            reverse('criar_ficha'),
            self.dados_ficha(aluno=self.outro_aluno),
        )
        resposta_historico = self.client.get(reverse('detalhe_ficha', args=[1]))

        self.assertEqual(resposta_criacao.status_code, 302)
        self.assertEqual(resposta_historico.status_code, 302)
        self.assertEqual(FichaTreino.objects.count(), 0)

    def test_ficha_ativa_inexistente_apresenta_mensagem_informativa(self):
        self.client.force_login(self.aluno.perfil.usuario)

        resposta = self.client.get(reverse('ficha_ativa_aluno'))

        self.assertContains(resposta, 'Você ainda não possui uma ficha de treino ativa')
