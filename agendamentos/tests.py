import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from itertools import count
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno
from financeiro.models import Cancelamento, Cobranca, Matricula, Plano, RegraFinanceira, Trancamento
from turmas.models import Modalidade, Turma

from . import servicos
from .models import Agendamento
from .servicos import AgendamentoNegado, agendar, cancelar_agendamento, modalidade_esta_no_plano

Status = Agendamento.Status
_sequencia = count(1)


class Fabrica:
    """Monta plano, modalidades, turma e alunos prontos para agendar."""

    def preparar_cenario(self):
        RegraFinanceira.obter()  # tolerância 3 dias, bloqueio a partir de 15
        self.hoje = timezone.localdate()
        self.yoga = Modalidade.objects.create(nome='Yoga')
        self.natacao = Modalidade.objects.create(nome='Natação')
        self.plano = self.novo_plano('Musculação, Yoga')
        usuario = User.objects.create_user(username='prof', password='senha12345')
        Perfil.objects.create(usuario=usuario, tipo=Perfil.PROFESSOR)
        self.professor = usuario

    def novo_plano(self, modalidades):
        return Plano.objects.create(
            nome=f'Plano {next(_sequencia)}', modalidades_incluidas=modalidades,
            periodicidade='mensal', valor=Decimal('100.00'), dia_vencimento=10,
        )

    def nova_turma(self, modalidade=None, capacidade=2, **extra):
        dados = dict(
            modalidade=modalidade or self.yoga, dia_semana='segunda', horario='18:00',
            professor=self.professor, sala='Sala 1', capacidade_maxima=capacidade, ativo=True,
        )
        dados.update(extra)
        return Turma.objects.create(**dados)

    def novo_aluno(self, plano=None):
        n = next(_sequencia)
        usuario = User.objects.create_user(username=f'aluna{n}', password='senha12345')
        perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.ALUNO)
        aluno = Aluno.objects.create(
            perfil=perfil, nome=f'Aluna {n}', cpf=f'{n:011d}', data_nascimento=date(2000, 1, 1),
            endereco='Rua A, 1', telefone=f'8199{n:07d}', email=f'aluna{n}@exemplo.com',
            contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
        )
        Matricula.objects.create(
            aluno=aluno, plano=plano or self.plano,
            data_inicio=self.hoje - timedelta(days=90), forma_pagamento='pix',
        )
        return aluno

    def matricula_de(self, aluno):
        return Matricula.objects.get(aluno=aluno)

    def atrasar(self, aluno, dias):
        """Cria uma mensalidade em aberto vencida há `dias` dias."""
        return Cobranca.objects.create(
            matricula=self.matricula_de(aluno), tipo='mensalidade', valor=Decimal('100.00'),
            vencimento=self.hoje - timedelta(days=dias), competencia=f'2026-{next(_sequencia):02d}',
        )

    def ativos(self, turma, status):
        return Agendamento.objects.filter(turma=turma, status=status)


# ===================================================================== regra do plano
class ModalidadeNoPlanoTests(SimpleTestCase):
    def esta(self, nome, texto):
        return modalidade_esta_no_plano(Modalidade(nome=nome), Plano(modalidades_incluidas=texto))

    def test_ignora_acento_e_maiuscula(self):
        self.assertTrue(self.esta('Dança', 'musculacao, DANCA, pilates'))
        self.assertTrue(self.esta('musculacao', 'Musculação'))

    def test_aceita_varios_separadores(self):
        texto = 'Yoga; Pilates e Natação\nSpinning / Dança'
        for nome in ('Yoga', 'Pilates', 'Natação', 'Spinning', 'Dança'):
            self.assertTrue(self.esta(nome, texto), nome)

    def test_exige_a_palavra_inteira(self):
        self.assertFalse(self.esta('Dança', 'Dançarino, Musculação'))
        self.assertFalse(self.esta('Spin', 'Spinning'))

    def test_modalidade_fora_do_plano(self):
        self.assertFalse(self.esta('Natação', 'Musculação, Yoga'))

    def test_vazios_nao_casam(self):
        self.assertFalse(self.esta('', 'Yoga'))
        self.assertFalse(self.esta('Yoga', ''))


# ===================================================================== regras de negócio
class AgendarEListaDeEsperaTests(Fabrica, TestCase):
    def setUp(self):
        self.preparar_cenario()

    def test_com_vaga_reserva(self):
        turma = self.nova_turma(capacidade=2)
        ag = agendar(self.novo_aluno(), turma.id)
        self.assertEqual(ag.status, Status.RESERVADO)
        self.assertEqual(turma.vagas_restantes(), 1)

    def test_turma_cheia_vai_para_a_espera_com_a_posicao_visivel(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (agendar(self.novo_aluno(), turma.id) for _ in range(3))
        self.assertEqual(a1.status, Status.RESERVADO)
        self.assertEqual((a2.status, a2.posicao_na_fila()), (Status.ESPERA, 1))
        self.assertEqual((a3.status, a3.posicao_na_fila()), (Status.ESPERA, 2))
        self.assertEqual(turma.vagas_restantes(), 0)

    def test_quem_reservou_nao_tem_posicao_na_fila(self):
        turma = self.nova_turma(capacidade=1)
        self.assertIsNone(agendar(self.novo_aluno(), turma.id).posicao_na_fila())

    def test_desistencia_libera_a_vaga_para_o_primeiro_da_fila(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (agendar(self.novo_aluno(), turma.id) for _ in range(3))
        _, promovidos = cancelar_agendamento(a1.aluno, a1.id)
        for ag in (a1, a2, a3):
            ag.refresh_from_db()
        self.assertEqual(a1.status, Status.CANCELADO)
        self.assertEqual(a2.status, Status.RESERVADO)
        self.assertEqual((a3.status, a3.posicao_na_fila()), (Status.ESPERA, 1))
        self.assertEqual([p.id for p in promovidos], [a2.id])
        self.assertEqual(turma.vagas_restantes(), 0)

    def test_a_vez_e_a_ordem_de_entrada_e_nao_a_ordem_do_cadastro(self):
        turma = self.nova_turma(capacidade=1)
        a, b, c, dono = (self.novo_aluno() for _ in range(4))
        agendar(dono, turma.id)
        ag_c = agendar(c, turma.id)  # c entrou na fila primeiro
        ag_a = agendar(a, turma.id)
        ag_b = agendar(b, turma.id)
        cancelar_agendamento(dono, Agendamento.objects.get(turma=turma, aluno=dono).id)
        for ag in (ag_c, ag_a, ag_b):
            ag.refresh_from_db()
        self.assertEqual(ag_c.status, Status.RESERVADO)
        self.assertEqual([ag_a.posicao_na_fila(), ag_b.posicao_na_fila()], [1, 2])

    def test_desistir_da_espera_nao_libera_vaga_e_reordena_a_fila(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (agendar(self.novo_aluno(), turma.id) for _ in range(3))
        cancelar_agendamento(a2.aluno, a2.id)
        for ag in (a1, a3):
            ag.refresh_from_db()
        self.assertEqual(a1.status, Status.RESERVADO)
        self.assertEqual((a3.status, a3.posicao_na_fila()), (Status.ESPERA, 1))

    def test_uma_desistencia_promove_so_uma_pessoa(self):
        turma = self.nova_turma(capacidade=2)
        a1, a2, a3, a4 = (agendar(self.novo_aluno(), turma.id) for _ in range(4))
        cancelar_agendamento(a1.aluno, a1.id)
        for ag in (a3, a4):
            ag.refresh_from_db()
        self.assertEqual(a3.status, Status.RESERVADO)
        self.assertEqual((a4.status, a4.posicao_na_fila()), (Status.ESPERA, 1))
        self.assertEqual(self.ativos(turma, Status.RESERVADO).count(), 2)

    def test_quem_cancela_e_volta_entra_no_fim_da_fila(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (agendar(self.novo_aluno(), turma.id) for _ in range(3))
        cancelar_agendamento(a2.aluno, a2.id)
        de_novo = agendar(a2.aluno, turma.id)
        a3.refresh_from_db()
        self.assertEqual(a3.posicao_na_fila(), 1)
        self.assertEqual(de_novo.posicao_na_fila(), 2)

    def test_a_fila_nao_e_furada_quando_a_capacidade_aumenta(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2 = (agendar(self.novo_aluno(), turma.id) for _ in range(2))
        turma.capacidade_maxima = 2
        turma.save()
        novo = agendar(self.novo_aluno(), turma.id)
        a2.refresh_from_db()
        self.assertEqual(a2.status, Status.RESERVADO)  # quem esperava ganha a vaga nova primeiro
        self.assertEqual((novo.status, novo.posicao_na_fila()), (Status.ESPERA, 1))

    def test_quem_ficou_sem_condicoes_e_pulado_mas_nao_perde_o_lugar(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (agendar(self.novo_aluno(), turma.id) for _ in range(3))
        atraso = self.atrasar(a2.aluno, 30)  # a2 foi bloqueada enquanto esperava
        cancelar_agendamento(a1.aluno, a1.id)
        for ag in (a2, a3):
            ag.refresh_from_db()
        self.assertEqual(a3.status, Status.RESERVADO)
        self.assertEqual((a2.status, a2.posicao_na_fila()), (Status.ESPERA, 1))
        atraso.paga = True
        atraso.save()
        cancelar_agendamento(a3.aluno, a3.id)
        a2.refresh_from_db()
        self.assertEqual(a2.status, Status.RESERVADO)


class QuemPodeAgendarTests(Fabrica, TestCase):
    def setUp(self):
        self.preparar_cenario()
        self.turma = self.nova_turma(capacidade=5)

    def assertNegado(self, aluno, trecho, turma=None):
        with self.assertRaisesMessage(AgendamentoNegado, trecho):
            agendar(aluno, (turma or self.turma).id)
        self.assertFalse(Agendamento.objects.filter(aluno=aluno).exists())

    def test_nao_agenda_modalidade_fora_do_plano(self):
        turma_natacao = self.nova_turma(modalidade=self.natacao)
        self.assertNegado(self.novo_aluno(), 'não está incluída no seu plano', turma_natacao)

    def test_plano_com_a_modalidade_agenda(self):
        plano_nat = self.novo_plano('Natação')
        turma_natacao = self.nova_turma(modalidade=self.natacao)
        self.assertEqual(agendar(self.novo_aluno(plano_nat), turma_natacao.id).status, Status.RESERVADO)

    def test_matricula_bloqueada_nao_agenda(self):
        aluno = self.novo_aluno()
        self.atrasar(aluno, 30)
        self.assertNegado(aluno, 'bloqueada')

    def test_matricula_trancada_nao_agenda(self):
        aluno = self.novo_aluno()
        Trancamento.objects.create(matricula=self.matricula_de(aluno), data_inicio=self.hoje)
        self.assertNegado(aluno, 'trancada')

    def test_matricula_cancelada_nao_agenda(self):
        aluno = self.novo_aluno()
        Cancelamento.objects.create(matricula=self.matricula_de(aluno))
        self.assertNegado(aluno, 'cancelada')

    def test_inadimplente_ainda_agenda(self):
        aluno = self.novo_aluno()
        self.atrasar(aluno, 5)  # passou da tolerância, mas ainda não bloqueou
        self.assertEqual(agendar(aluno, self.turma.id).status, Status.RESERVADO)

    def test_pagar_o_atraso_devolve_o_direito_de_agendar(self):
        aluno = self.novo_aluno()
        atraso = self.atrasar(aluno, 30)
        self.assertNegado(aluno, 'bloqueada')
        atraso.paga = True
        atraso.save()
        self.assertEqual(agendar(aluno, self.turma.id).status, Status.RESERVADO)

    def test_aluno_sem_matricula_nao_agenda(self):
        aluno = self.novo_aluno()
        Matricula.objects.filter(aluno=aluno).delete()
        self.assertNegado(aluno, 'não tem matrícula')

    def test_turma_inativa_nao_recebe_agendamento(self):
        self.turma.ativo = False
        self.turma.save()
        self.assertNegado(self.novo_aluno(), 'não está mais ativa')

    def test_turma_inexistente(self):
        with self.assertRaisesMessage(AgendamentoNegado, 'Turma não encontrada'):
            agendar(self.novo_aluno(), 999999)

    def test_nao_agenda_duas_vezes_a_mesma_turma(self):
        aluno = self.novo_aluno()
        agendar(aluno, self.turma.id)
        with self.assertRaisesMessage(AgendamentoNegado, 'Você já está nesta turma'):
            agendar(aluno, self.turma.id)
        self.assertEqual(Agendamento.objects.filter(aluno=aluno).count(), 1)

    def test_o_banco_tambem_recusa_agendamento_ativo_duplicado(self):
        aluno = self.novo_aluno()
        Agendamento.objects.create(turma=self.turma, aluno=aluno, status=Status.ESPERA)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Agendamento.objects.create(turma=self.turma, aluno=aluno, status=Status.RESERVADO)

    def test_o_banco_aceita_novo_agendamento_depois_de_cancelado(self):
        aluno = self.novo_aluno()
        Agendamento.objects.create(turma=self.turma, aluno=aluno, status=Status.CANCELADO)
        Agendamento.objects.create(turma=self.turma, aluno=aluno, status=Status.RESERVADO)


class CancelarTests(Fabrica, TestCase):
    def setUp(self):
        self.preparar_cenario()
        self.turma = self.nova_turma(capacidade=2)

    def test_aluno_cancela_o_proprio_agendamento(self):
        aluno = self.novo_aluno()
        ag = agendar(aluno, self.turma.id)
        cancelar_agendamento(aluno, ag.id)
        ag.refresh_from_db()
        self.assertEqual(ag.status, Status.CANCELADO)
        self.assertIsNotNone(ag.cancelado_em)
        self.assertEqual(self.turma.vagas_restantes(), 2)

    def test_nao_cancela_o_agendamento_de_outro_aluno(self):
        dono, intruso = self.novo_aluno(), self.novo_aluno()
        ag = agendar(dono, self.turma.id)
        with self.assertRaisesMessage(AgendamentoNegado, 'não encontrado'):
            cancelar_agendamento(intruso, ag.id)
        ag.refresh_from_db()
        self.assertEqual(ag.status, Status.RESERVADO)

    def test_nao_cancela_duas_vezes(self):
        aluno = self.novo_aluno()
        ag = agendar(aluno, self.turma.id)
        cancelar_agendamento(aluno, ag.id)
        with self.assertRaisesMessage(AgendamentoNegado, 'já foi cancelado'):
            cancelar_agendamento(aluno, ag.id)


class TurmaComAgendamentosTests(Fabrica, TestCase):
    """Os dois ganchos que a T04 deixou prontos na Turma."""

    def setUp(self):
        self.preparar_cenario()
        self.turma = self.nova_turma(capacidade=1)

    def test_tem_aluno_agendado_considera_reserva_e_espera(self):
        self.assertFalse(self.turma.tem_aluno_agendado())
        a1, a2 = (agendar(self.novo_aluno(), self.turma.id) for _ in range(2))
        self.assertTrue(self.turma.tem_aluno_agendado())
        cancelar_agendamento(a1.aluno, a1.id)   # a2 sobe para a vaga
        cancelar_agendamento(a2.aluno, a2.id)
        self.assertFalse(self.turma.tem_aluno_agendado())

    def test_o_banco_nao_deixa_excluir_turma_com_agendamento(self):
        from django.db.models import ProtectedError
        agendar(self.novo_aluno(), self.turma.id)
        with self.assertRaises(ProtectedError):
            self.turma.delete()

    def test_api_de_turmas_mostra_os_matriculados_reais(self):
        agendar(self.novo_aluno(), self.turma.id)
        agendar(self.novo_aluno(), self.turma.id)  # fica na espera, não conta como vaga ocupada
        dados = self.client.get('/api/turmas/').json()
        turma = next(t for t in dados if t['id'] == self.turma.id)
        self.assertEqual((turma['capacity'], turma['enrolled']), (1, 1))


# ===================================================================== telas do aluno
class TelasDoAlunoTests(Fabrica, TestCase):
    def setUp(self):
        self.preparar_cenario()
        self.turma = self.nova_turma(capacidade=1)
        self.turma_natacao = self.nova_turma(modalidade=self.natacao)
        self.aluno = self.novo_aluno()
        self.entrar(self.aluno)

    def entrar(self, aluno):
        self.client.logout()
        self.client.login(username=aluno.perfil.usuario.username, password='senha12345')

    def test_visitante_vai_para_o_login(self):
        self.client.logout()
        self.assertEqual(self.client.get('/agendamentos/').status_code, 302)

    def test_professor_nao_acessa_a_tela_do_aluno(self):
        self.client.logout()
        self.client.login(username='prof', password='senha12345')
        resposta = self.client.get('/agendamentos/')
        self.assertRedirects(resposta, '/painel/', fetch_redirect_response=False)

    def test_lista_so_as_turmas_do_plano_com_as_vagas_restantes(self):
        resposta = self.client.get('/agendamentos/')
        self.assertContains(resposta, 'Yoga')
        self.assertNotContains(resposta, 'Natação')
        self.assertContains(resposta, '1 de 1')

    def test_reservar_pela_tela(self):
        resposta = self.client.post(f'/agendamentos/turmas/{self.turma.id}/agendar/', follow=True)
        self.assertContains(resposta, 'Vaga reservada')
        self.assertTrue(self.ativos(self.turma, Status.RESERVADO).filter(aluno=self.aluno).exists())

    def test_turma_cheia_mostra_a_posicao_na_lista_de_espera(self):
        agendar(self.novo_aluno(), self.turma.id)
        resposta = self.client.post(f'/agendamentos/turmas/{self.turma.id}/agendar/', follow=True)
        self.assertContains(resposta, 'lista de espera')
        self.assertContains(resposta, 'posição 1º')

    def test_agendar_exige_post(self):
        self.assertEqual(self.client.get(f'/agendamentos/turmas/{self.turma.id}/agendar/').status_code, 405)

    def test_matricula_bloqueada_ve_o_aviso_e_nao_agenda(self):
        self.atrasar(self.aluno, 30)
        self.assertContains(self.client.get('/agendamentos/'), 'Agendamento indisponível')
        resposta = self.client.post(f'/agendamentos/turmas/{self.turma.id}/agendar/', follow=True)
        self.assertContains(resposta, 'bloqueada')
        self.assertFalse(Agendamento.objects.exists())

    def test_cancelar_pela_tela(self):
        ag = agendar(self.aluno, self.turma.id)
        resposta = self.client.post(f'/agendamentos/{ag.id}/cancelar/', follow=True)
        self.assertContains(resposta, 'Agendamento cancelado')
        ag.refresh_from_db()
        self.assertEqual(ag.status, Status.CANCELADO)

    def test_nao_cancela_pela_tela_o_agendamento_de_outra_aluna(self):
        outra = self.novo_aluno()
        ag = agendar(outra, self.turma.id)
        resposta = self.client.post(f'/agendamentos/{ag.id}/cancelar/', follow=True)
        self.assertContains(resposta, 'não encontrado')
        ag.refresh_from_db()
        self.assertEqual(ag.status, Status.RESERVADO)


# ===================================================================== concorrência (só PostgreSQL)
@skipUnlessDBFeature('has_select_for_update')
class ConcorrenciaTests(Fabrica, TransactionTestCase):
    """Várias conexões ao mesmo tempo, de verdade. Só roda em bancos com trava de linha
    (PostgreSQL); no SQLite é ignorado, porque lá o teste não provaria nada.

    O `_vagas_livres` é propositalmente retardado: isso alarga a janela entre
    "conferir se tem vaga" e "gravar", que é onde a corrida acontece. Sem a
    trava da turma, todo mundo enxergaria a mesma vaga livre e o teste falharia.
    """

    def setUp(self):
        self.preparar_cenario()

    def disputar(self, tarefas):
        original = servicos._vagas_livres

        def devagar(turma):
            livres = original(turma)
            time.sleep(0.05)
            return livres

        barreira = threading.Barrier(len(tarefas))
        resultados, erros = [], []

        def executar(tarefa):
            try:
                barreira.wait(timeout=15)
                resultados.append(tarefa())
            except Exception as erro:  # noqa: BLE001 (queremos ver qualquer falha)
                erros.append(erro)
            finally:
                connections.close_all()

        with mock.patch.object(servicos, '_vagas_livres', devagar):
            threads = [threading.Thread(target=executar, args=(t,)) for t in tarefas]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
        return resultados, erros

    def test_oito_pessoas_disputam_a_ultima_vaga_e_so_uma_fica_com_ela(self):
        turma = self.nova_turma(capacidade=1)
        alunos = [self.novo_aluno() for _ in range(8)]
        _, erros = self.disputar([lambda a=a: agendar(a, turma.id) for a in alunos])
        self.assertEqual(erros, [])
        self.assertEqual(self.ativos(turma, Status.RESERVADO).count(), 1)
        esperando = list(self.ativos(turma, Status.ESPERA))
        self.assertEqual(len(esperando), 7)
        self.assertEqual(sorted(ag.posicao_na_fila() for ag in esperando), [1, 2, 3, 4, 5, 6, 7])

    def test_dez_pessoas_para_tres_vagas(self):
        turma = self.nova_turma(capacidade=3)
        alunos = [self.novo_aluno() for _ in range(10)]
        _, erros = self.disputar([lambda a=a: agendar(a, turma.id) for a in alunos])
        self.assertEqual(erros, [])
        self.assertEqual(self.ativos(turma, Status.RESERVADO).count(), 3)
        self.assertEqual(self.ativos(turma, Status.ESPERA).count(), 7)

    def test_duplo_clique_da_mesma_aluna_gera_um_so_agendamento(self):
        turma = self.nova_turma(capacidade=5)
        aluno = self.novo_aluno()
        resultados, erros = self.disputar([lambda: agendar(aluno, turma.id) for _ in range(2)])
        self.assertEqual(len(resultados), 1)
        self.assertEqual([type(e) for e in erros], [AgendamentoNegado])
        self.assertEqual(Agendamento.objects.filter(aluno=aluno).count(), 1)

    def test_duas_desistencias_ao_mesmo_tempo_promovem_pessoas_diferentes(self):
        turma = self.nova_turma(capacidade=2)
        a1, a2, a3, a4, a5 = (self.novo_aluno() for _ in range(5))
        ags = {a: agendar(a, turma.id) for a in (a1, a2, a3, a4, a5)}
        _, erros = self.disputar([
            lambda: cancelar_agendamento(a1, ags[a1].id),
            lambda: cancelar_agendamento(a2, ags[a2].id),
        ])
        self.assertEqual(erros, [])
        reservados = {ag.aluno_id for ag in self.ativos(turma, Status.RESERVADO)}
        self.assertEqual(reservados, {a3.id, a4.id})
        self.assertEqual(self.ativos(turma, Status.ESPERA).get().aluno_id, a5.id)

    def test_desistencia_e_novo_agendamento_ao_mesmo_tempo_respeitam_a_fila(self):
        turma = self.nova_turma(capacidade=1)
        a1, a2, a3 = (self.novo_aluno() for _ in range(3))
        ag1, _ag2 = agendar(a1, turma.id), agendar(a2, turma.id)
        _, erros = self.disputar([
            lambda: cancelar_agendamento(a1, ag1.id),
            lambda: agendar(a3, turma.id),
        ])
        self.assertEqual(erros, [])
        self.assertEqual(self.ativos(turma, Status.RESERVADO).get().aluno_id, a2.id)
        self.assertEqual(self.ativos(turma, Status.ESPERA).get().aluno_id, a3.id)
