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
from treinos.models import ExecucaoExercicio, ExercicioTreino, FichaTreino
from turmas.models import Frequencia as PresencaAula, Modalidade, Turma

from .servicos import (
    evolucao_de_carga, frequencia_no_periodo, normalizar_periodo, presenca_em_aulas_no_periodo,
)


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
        resposta = self.client.get(self.url, {'a': a2.pk, 'b': a1.pk})
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


class PresencaAulasTests(BaseRetencaoTest):
    def setUp(self):
        super().setUp()
        self.zumba = Modalidade.objects.create(nome='Zumba')
        self.yoga = Modalidade.objects.create(nome='Yoga')
        self.turma_zumba = self.turma(self.zumba)
        self.turma_yoga = self.turma(self.yoga)

    def turma(self, modalidade):
        return Turma.objects.create(
            modalidade=modalidade, dia_semana='segunda', horario='08:00',
            professor=self.professor, sala='A', capacidade_maxima=10,
        )

    def chamada(self, aluno, turma, dias_atras, presente):
        return PresencaAula.objects.create(
            turma=turma, aluno=aluno.perfil.usuario,
            data=self.hoje - timedelta(days=dias_atras), presente=presente,
        )

    def test_conta_presencas_e_faltas_por_modalidade(self):
        self.chamada(self.aluna, self.turma_zumba, 1, True)
        self.chamada(self.aluna, self.turma_zumba, 2, True)
        self.chamada(self.aluna, self.turma_zumba, 3, False)
        self.chamada(self.aluna, self.turma_yoga, 4, True)
        r = presenca_em_aulas_no_periodo(self.aluna, '30')
        self.assertEqual((r['presencas'], r['faltas'], r['total']), (3, 1, 4))
        self.assertEqual(r['percentual'], 75)
        self.assertEqual(
            [(i['modalidade'], i['presencas'], i['faltas']) for i in r['por_modalidade']],
            [('Yoga', 1, 0), ('Zumba', 2, 1)],
        )

    def test_respeita_o_periodo(self):
        self.chamada(self.aluna, self.turma_zumba, 2, True)
        self.chamada(self.aluna, self.turma_zumba, 20, True)
        self.assertEqual(presenca_em_aulas_no_periodo(self.aluna, '7')['presencas'], 1)
        self.assertEqual(presenca_em_aulas_no_periodo(self.aluna, '30')['presencas'], 2)

    def test_nao_conta_presenca_de_outra_aluna(self):
        self.chamada(self.outra, self.turma_zumba, 1, True)
        self.assertEqual(presenca_em_aulas_no_periodo(self.aluna, '30')['total'], 0)

    def test_sem_chamada_nao_tem_percentual(self):
        r = presenca_em_aulas_no_periodo(self.aluna, '30')
        self.assertEqual(r['total'], 0)
        self.assertIsNone(r['percentual'])

    def test_tela_mostra_presencas(self):
        self.chamada(self.aluna, self.turma_zumba, 1, True)
        self.chamada(self.aluna, self.turma_zumba, 2, False)
        self.entrar_como('ana')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Presença nas aulas coletivas')
        self.assertContains(resp, 'Zumba')
        self.assertContains(resp, '50%')

    def test_tela_sem_chamada_mostra_aviso(self):
        self.entrar_como('ana')
        self.assertContains(self.client.get(self.url), 'Nenhuma aula coletiva com chamada')


class EvolucaoCargaTests(BaseRetencaoTest):
    def setUp(self):
        super().setUp()
        self.ficha = FichaTreino.objects.create(
            aluno=self.aluna, professor=self.professor, data_revisao=self.hoje + timedelta(days=30),
        )
        self.agacho = ExercicioTreino.objects.create(ficha=self.ficha, nome='Agachamento')
        self.remada = ExercicioTreino.objects.create(ficha=self.ficha, nome='Remada')

    def execucao(self, exercicio, carga, dias_atras, aluno=None):
        return ExecucaoExercicio.objects.create(
            aluno=aluno or self.aluna, exercicio=exercicio, carga_kg=Decimal(carga),
            data=self.hoje - timedelta(days=dias_atras),
        )

    def test_evolucao_por_exercicio_em_ordem_cronologica(self):
        self.execucao(self.agacho, '30', 0)
        self.execucao(self.agacho, '20', 20)
        self.execucao(self.agacho, '25', 10)
        self.execucao(self.remada, '10', 5)
        r = {g['nome']: g for g in evolucao_de_carga(self.aluna)}
        ag = r['Agachamento']
        self.assertEqual([x.carga_kg for x in ag['registros']], [Decimal('20'), Decimal('25'), Decimal('30')])
        self.assertEqual((ag['primeira'], ag['ultima'], ag['maior'], ag['diferenca']),
                         (Decimal('20'), Decimal('30'), Decimal('30'), Decimal('10')))
        self.assertIsNone(r['Remada']['diferenca'])

    def test_serie_continua_quando_a_ficha_e_trocada(self):
        self.execucao(self.agacho, '20', 30)
        self.ficha.encerrar()
        nova = FichaTreino.objects.create(
            aluno=self.aluna, professor=self.professor, data_revisao=self.hoje + timedelta(days=30),
        )
        novo = ExercicioTreino.objects.create(ficha=nova, nome='  agachamento ')
        self.execucao(novo, '35', 0)
        grupos = evolucao_de_carga(self.aluna)
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]['quantidade'], 2)
        self.assertEqual(grupos[0]['diferenca'], Decimal('15'))

    def test_nao_mistura_execucoes_de_outra_aluna(self):
        self.execucao(self.agacho, '20', 1, aluno=self.outra)
        self.assertEqual(evolucao_de_carga(self.aluna), [])

    def test_tela_mostra_evolucao(self):
        self.execucao(self.agacho, '20', 10)
        self.execucao(self.agacho, '27.5', 0)
        self.entrar_como('ana')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Evolução da carga por exercício')
        self.assertContains(resp, 'Agachamento')
        self.assertContains(resp, '+7,50 kg')

    def test_aluna_sem_execucao_ve_aviso_sem_erro(self):
        self.entrar_como('ana')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ainda não registrou nenhuma carga')


class RegistrarExecucaoTests(BaseRetencaoTest):
    def setUp(self):
        super().setUp()
        self.ficha = FichaTreino.objects.create(
            aluno=self.aluna, professor=self.professor, data_revisao=self.hoje + timedelta(days=30),
        )
        self.ex = ExercicioTreino.objects.create(ficha=self.ficha, nome='Agachamento')
        self.url_reg = reverse('registrar_execucao', args=[self.ex.pk])

    def test_aluna_registra_carga(self):
        self.entrar_como('ana')
        resp = self.client.post(self.url_reg, {
            'data': self.hoje.isoformat(), 'carga_kg': '22.5', 'series': '3', 'repeticoes': '12',
        })
        self.assertRedirects(resp, reverse('ficha_ativa_aluno'))
        e = ExecucaoExercicio.objects.get()
        self.assertEqual((e.aluno, e.exercicio, e.carga_kg, e.series), (self.aluna, self.ex, Decimal('22.50'), 3))

    def test_recusa_carga_negativa_e_data_futura(self):
        self.entrar_como('ana')
        self.client.post(self.url_reg, {'data': self.hoje.isoformat(), 'carga_kg': '-5'})
        self.client.post(self.url_reg, {
            'data': (self.hoje + timedelta(days=1)).isoformat(), 'carga_kg': '10',
        })
        self.assertEqual(ExecucaoExercicio.objects.count(), 0)

    def test_nao_registra_em_exercicio_de_outra_aluna(self):
        self.entrar_como('bia')
        resp = self.client.post(self.url_reg, {'data': self.hoje.isoformat(), 'carga_kg': '10'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ExecucaoExercicio.objects.count(), 0)

    def test_nao_registra_em_ficha_encerrada(self):
        self.ficha.encerrar()
        self.entrar_como('ana')
        resp = self.client.post(self.url_reg, {'data': self.hoje.isoformat(), 'carga_kg': '10'})
        self.assertEqual(resp.status_code, 404)

    def test_professor_nao_registra_e_get_nao_permitido(self):
        self.entrar_como('prof')
        self.client.post(self.url_reg, {'data': self.hoje.isoformat(), 'carga_kg': '10'})
        self.assertEqual(ExecucaoExercicio.objects.count(), 0)
        self.client.logout()
        self.entrar_como('ana')
        self.assertEqual(self.client.get(self.url_reg).status_code, 405)

    def test_ficha_da_aluna_mostra_formulario_de_carga(self):
        self.entrar_como('ana')
        self.assertContains(self.client.get(reverse('ficha_ativa_aluno')), 'Registrar treino')
