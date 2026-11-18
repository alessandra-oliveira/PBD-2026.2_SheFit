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
from django.core.exceptions import ValidationError

from .models import (
    Execucao, ExecucaoExercicio, ExercicioTreino, FichaTreino,
    RegistroImutavelError,
)
from .servicos import aderencia, evolucao_carga, registrar_execucao


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

def criar_aluno_t14(username, cpf, nome):
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


class BaseExecucaoTests(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.professor = User.objects.create_user(username='prof14', password='senha12345')
        Perfil.objects.create(usuario=self.professor, tipo=Perfil.PROFESSOR)
        self.aluno = criar_aluno_t14('aluna14', '12345678911', 'Ana T14')
        self.outro_aluno = criar_aluno_t14('outra14', '12345678912', 'Bia T14')

        self.ficha = FichaTreino.objects.create(
            aluno=self.aluno, professor=self.professor,
            data_revisao=self.hoje + timedelta(days=30),
        )
        self.agachamento = ExercicioTreino.objects.create(
            ficha=self.ficha, nome='Agachamento', series=3, repeticoes=12,
            carga_sugerida=Decimal('20.00'),
        )
        self.remada = ExercicioTreino.objects.create(
            ficha=self.ficha, nome='Remada', carga_sugerida=Decimal('15.00'),
        )

        self.ficha_outra = FichaTreino.objects.create(
            aluno=self.outro_aluno, professor=self.professor,
            data_revisao=self.hoje + timedelta(days=30),
        )
        self.exercicio_alheio = ExercicioTreino.objects.create(
            ficha=self.ficha_outra, nome='Exercício alheio',
        )

    def recuar_ficha(self, dias=40):
        """Ficha criada há alguns dias, para poder registrar treinos em datas passadas."""
        FichaTreino.objects.filter(pk=self.ficha.pk).update(
            criada_em=timezone.now() - timedelta(days=dias),
        )

    def registrar(self, *exercicios_e_cargas, data=None, observacoes=''):
        itens = [
            {'exercicio_id': exercicio.pk, 'carga_efetiva': carga}
            for exercicio, carga in exercicios_e_cargas
        ]
        return registrar_execucao(self.aluno, itens, observacoes, data)


class RegistrarExecucaoServicoTests(BaseExecucaoTests):
    def test_registra_execucao_com_copia_dos_dados_da_ficha(self):
        execucao = self.registrar(
            (self.agachamento, Decimal('22.50')), observacoes='  foi bem  ',
        )

        self.assertEqual(execucao.aluno, self.aluno)
        self.assertEqual(execucao.ficha, self.ficha)
        self.assertEqual(execucao.data, self.hoje)
        self.assertEqual(execucao.observacoes, 'foi bem')
        self.assertEqual(execucao.total_prescritos, 2)
        item = execucao.itens.get()
        self.assertEqual(item.nome, 'Agachamento')
        self.assertEqual(item.carga_prescrita, Decimal('20.00'))
        self.assertEqual(item.carga_efetiva, Decimal('22.50'))

    def test_editar_o_exercicio_depois_nao_muda_o_historico(self):
        execucao = self.registrar((self.agachamento, Decimal('22.50')))

        ExercicioTreino.objects.filter(pk=self.agachamento.pk).update(
            nome='Renomeado', carga_sugerida=Decimal('99.00'),
        )

        item = execucao.itens.get()
        self.assertEqual(item.nome, 'Agachamento')
        self.assertEqual(item.carga_prescrita, Decimal('20.00'))

    def test_apagar_o_exercicio_mantem_o_historico(self):
        execucao = self.registrar((self.agachamento, Decimal('22.50')))

        self.agachamento.delete()

        item = execucao.itens.get()
        self.assertEqual(item.nome, 'Agachamento')
        self.assertIsNone(item.exercicio)

    def test_carga_pode_ficar_em_branco(self):
        execucao = self.registrar((self.agachamento, None))
        self.assertIsNone(execucao.itens.get().carga_efetiva)

    def test_sem_ficha_ativa_e_recusado(self):
        self.ficha.encerrar()
        with self.assertRaises(ValidationError):
            self.registrar((self.agachamento, Decimal('10')))
        self.assertEqual(Execucao.objects.count(), 0)

    def test_sem_exercicio_marcado_e_recusado(self):
        with self.assertRaises(ValidationError):
            registrar_execucao(self.aluno, [], 'nada')
        self.assertEqual(Execucao.objects.count(), 0)

    def test_data_futura_e_recusada(self):
        with self.assertRaises(ValidationError):
            self.registrar(
                (self.agachamento, Decimal('10')), data=self.hoje + timedelta(days=1),
            )
        self.assertEqual(Execucao.objects.count(), 0)

    def test_data_anterior_a_criacao_da_ficha_e_recusada(self):
        with self.assertRaises(ValidationError):
            self.registrar(
                (self.agachamento, Decimal('10')), data=self.hoje - timedelta(days=1),
            )
        self.assertEqual(Execucao.objects.count(), 0)

    def test_carga_negativa_e_recusada(self):
        with self.assertRaises(ValidationError):
            self.registrar((self.agachamento, Decimal('-1')))
        self.assertEqual(Execucao.objects.count(), 0)

    def test_exercicio_de_outra_ficha_e_recusado(self):
        with self.assertRaises(ValidationError):
            self.registrar((self.exercicio_alheio, Decimal('10')))
        self.assertEqual(Execucao.objects.count(), 0)

    def test_exercicio_repetido_e_recusado(self):
        with self.assertRaises(ValidationError):
            self.registrar(
                (self.agachamento, Decimal('10')), (self.agachamento, Decimal('12')),
            )
        self.assertEqual(Execucao.objects.count(), 0)
        self.assertEqual(ExecucaoExercicio.objects.count(), 0)


class ImutabilidadeExecucaoTests(BaseExecucaoTests):
    def setUp(self):
        super().setUp()
        self.execucao = self.registrar((self.agachamento, Decimal('22.50')), observacoes='original')
        self.item = self.execucao.itens.get()

    def test_execucao_nao_pode_ser_alterada(self):
        self.execucao.observacoes = 'mudei'
        with self.assertRaises(RegistroImutavelError):
            self.execucao.save()
        self.execucao.refresh_from_db()
        self.assertEqual(self.execucao.observacoes, 'original')

    def test_execucao_nao_pode_ser_apagada(self):
        with self.assertRaises(RegistroImutavelError):
            self.execucao.delete()
        self.assertTrue(Execucao.objects.filter(pk=self.execucao.pk).exists())

    def test_item_nao_pode_ser_alterado_nem_apagado(self):
        self.item.carga_efetiva = Decimal('99.00')
        with self.assertRaises(RegistroImutavelError):
            self.item.save()
        with self.assertRaises(RegistroImutavelError):
            self.item.delete()
        self.item.refresh_from_db()
        self.assertEqual(self.item.carga_efetiva, Decimal('22.50'))

    def test_atualizacao_e_exclusao_em_lote_sao_barradas(self):
        with self.assertRaises(RegistroImutavelError):
            Execucao.objects.update(observacoes='mudei')
        with self.assertRaises(RegistroImutavelError):
            Execucao.objects.filter(pk=self.execucao.pk).delete()
        with self.assertRaises(RegistroImutavelError):
            ExecucaoExercicio.objects.update(carga_efetiva=Decimal('1.00'))
        with self.assertRaises(RegistroImutavelError):
            ExecucaoExercicio.objects.all().delete()
        self.execucao.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.execucao.observacoes, 'original')
        self.assertEqual(self.item.carga_efetiva, Decimal('22.50'))


class AderenciaEEvolucaoTests(BaseExecucaoTests):
    def test_aderencia_soma_feitos_sobre_prescritos(self):
        self.recuar_ficha()
        self.registrar((self.agachamento, Decimal('20')), data=self.hoje - timedelta(days=2))
        self.registrar(
            (self.agachamento, Decimal('22')), (self.remada, Decimal('15')),
            data=self.hoje,
        )

        resultado = aderencia(self.aluno, self.hoje - timedelta(days=5), self.hoje)

        self.assertEqual(resultado['treinos'], 2)
        self.assertEqual(resultado['feitos'], 3)
        self.assertEqual(resultado['prescritos'], 4)
        self.assertEqual(resultado['percentual'], 75)

    def test_aderencia_respeita_o_periodo(self):
        self.recuar_ficha()
        self.registrar((self.agachamento, Decimal('20')), data=self.hoje - timedelta(days=20))
        self.registrar((self.agachamento, Decimal('22')), data=self.hoje)

        resultado = aderencia(self.aluno, self.hoje - timedelta(days=5), self.hoje)

        self.assertEqual(resultado['treinos'], 1)
        self.assertEqual(resultado['feitos'], 1)

    def test_aderencia_nao_mistura_alunos(self):
        self.registrar((self.agachamento, Decimal('20')))
        resultado = aderencia(self.outro_aluno, self.hoje - timedelta(days=5), self.hoje)
        self.assertEqual(resultado['treinos'], 0)

    def test_aderencia_sem_treinos_e_zero(self):
        resultado = aderencia(self.aluno, self.hoje - timedelta(days=30), self.hoje)
        self.assertEqual(
            resultado, {'treinos': 0, 'feitos': 0, 'prescritos': 0, 'percentual': 0},
        )

    def test_evolucao_em_ordem_de_data_ignorando_carga_em_branco(self):
        self.recuar_ficha()
        self.registrar((self.agachamento, Decimal('12')), data=self.hoje)
        self.registrar((self.agachamento, Decimal('8')), data=self.hoje - timedelta(days=3))
        self.registrar((self.agachamento, None), data=self.hoje - timedelta(days=1))

        evolucao = evolucao_carga(self.aluno)

        self.assertEqual(
            evolucao['Agachamento'],
            [
                (self.hoje - timedelta(days=3), Decimal('8.00')),
                (self.hoje, Decimal('12.00')),
            ],
        )


class ExecucaoViewsTests(BaseExecucaoTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.aluno.perfil.usuario)
        self.url_registrar = reverse('registrar_execucao_aluno')

    def dados(self, **extras):
        dados = {
            f'feito_{self.agachamento.pk}': '1',
            f'carga_{self.agachamento.pk}': '22,5',
            'observacoes': 'foi bem',
        }
        dados.update(extras)
        return dados

    def test_post_registra_o_treino_e_volta_para_a_ficha(self):
        resposta = self.client.post(self.url_registrar, self.dados())

        self.assertRedirects(
            resposta, reverse('ficha_ativa_aluno'), fetch_redirect_response=False,
        )
        execucao = Execucao.objects.get()
        self.assertEqual(execucao.aluno, self.aluno)
        self.assertEqual(execucao.observacoes, 'foi bem')
        self.assertEqual(execucao.itens.get().carga_efetiva, Decimal('22.50'))

    def test_post_sem_marcar_nada_nao_registra_e_avisa(self):
        resposta = self.client.post(self.url_registrar, {'observacoes': 'nada'}, follow=True)

        self.assertEqual(Execucao.objects.count(), 0)
        textos = [str(m) for m in resposta.context['messages']]
        self.assertTrue(any('Marque pelo menos um exercício' in t for t in textos))

    def test_carga_invalida_nao_registra(self):
        for carga in ('abc', '-5', '1e9'):
            resposta = self.client.post(
                self.url_registrar,
                self.dados(**{f'carga_{self.agachamento.pk}': carga}),
            )
            self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Execucao.objects.count(), 0)

    def test_data_invalida_ou_futura_nao_registra(self):
        futura = (self.hoje + timedelta(days=1)).isoformat()
        for data in ('31/02/2026', 'abc', futura):
            resposta = self.client.post(self.url_registrar, self.dados(data=data))
            self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Execucao.objects.count(), 0)

    def test_get_nao_registra_nada(self):
        resposta = self.client.get(self.url_registrar)
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Execucao.objects.count(), 0)

    def test_exercicio_de_outra_aluna_e_ignorado(self):
        resposta = self.client.post(
            self.url_registrar, {f'feito_{self.exercicio_alheio.pk}': '1'},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Execucao.objects.count(), 0)

    def test_professor_nao_registra_treino(self):
        self.client.force_login(self.professor)
        resposta = self.client.post(self.url_registrar, self.dados())
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Execucao.objects.count(), 0)

    def test_ficha_mostra_o_formulario_de_registro(self):
        resposta = self.client.get(reverse('ficha_ativa_aluno'))
        self.assertContains(resposta, 'Registrar treino')
        self.assertContains(resposta, f'name="feito_{self.agachamento.pk}"')
        self.assertContains(resposta, f'name="carga_{self.agachamento.pk}"')

    def test_aluna_sem_ficha_nao_ve_o_formulario(self):
        sem_ficha = criar_aluno_t14('semficha', '12345678913', 'Sem Ficha')
        self.client.force_login(sem_ficha.perfil.usuario)
        resposta = self.client.get(reverse('ficha_ativa_aluno'))
        self.assertNotContains(resposta, 'Registrar treino')

    def test_evolucao_mostra_so_as_cargas_da_propria_aluna(self):
        self.recuar_ficha()
        self.registrar((self.agachamento, Decimal('8')), data=self.hoje - timedelta(days=1))
        self.registrar((self.agachamento, Decimal('12')), data=self.hoje)
        registrar_execucao(
            self.outro_aluno,
            [{'exercicio_id': self.exercicio_alheio.pk, 'carga_efetiva': Decimal('50')}],
        )

        resposta = self.client.get(reverse('evolucao_aluno'))

        exercicios = resposta.context['exercicios']
        self.assertEqual([e['nome'] for e in exercicios], ['Agachamento'])
        self.assertEqual(exercicios[0]['inicial'], Decimal('8.00'))
        self.assertEqual(exercicios[0]['atual'], Decimal('12.00'))
        self.assertEqual(exercicios[0]['variacao'], Decimal('4.00'))
        self.assertNotContains(resposta, 'Exercício alheio')

    def test_evolucao_sem_treinos_mostra_aviso(self):
        resposta = self.client.get(reverse('evolucao_aluno'))
        self.assertContains(resposta, 'ainda não registrou nenhum treino')

    def test_professor_ve_historico_e_aderencia(self):
        self.registrar((self.agachamento, Decimal('22.50')), observacoes='foi bem')
        self.client.force_login(self.professor)

        resposta = self.client.get(reverse('execucoes_aluno', args=[self.aluno.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context['execucoes']), 1)
        self.assertEqual(resposta.context['aderencia']['percentual'], 50)
        self.assertContains(resposta, 'Agachamento')
        self.assertContains(resposta, 'foi bem')

    def test_filtro_de_periodo_na_tela_do_professor(self):
        self.recuar_ficha()
        self.registrar((self.agachamento, Decimal('20')), data=self.hoje - timedelta(days=20))
        self.client.force_login(self.professor)
        url = reverse('execucoes_aluno', args=[self.aluno.pk])

        padrao = self.client.get(url)
        recente = self.client.get(url, {
            'inicio': (self.hoje - timedelta(days=5)).isoformat(),
            'fim': self.hoje.isoformat(),
        })

        self.assertEqual(len(padrao.context['execucoes']), 1)
        self.assertEqual(len(recente.context['execucoes']), 0)

    def test_data_invalida_no_filtro_nao_quebra_a_tela(self):
        self.client.force_login(self.professor)
        resposta = self.client.get(
            reverse('execucoes_aluno', args=[self.aluno.pk]),
            {'inicio': 'abc', 'fim': 'xyz'},
        )
        self.assertEqual(resposta.status_code, 200)

    def test_aluna_nao_acessa_a_tela_do_professor(self):
        resposta = self.client.get(reverse('execucoes_aluno', args=[self.aluno.pk]))
        self.assertEqual(resposta.status_code, 302)

    def test_aluna_inexistente_da_404_para_o_professor(self):
        self.client.force_login(self.professor)
        resposta = self.client.get(reverse('execucoes_aluno', args=[999999]))
        self.assertEqual(resposta.status_code, 404)