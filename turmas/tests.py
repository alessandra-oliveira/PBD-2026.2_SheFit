from datetime import time
from itertools import count

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Perfil
from .models import Modalidade, Turma

_seq = count(1)


def criar_usuario(tipo):
    n = next(_seq)
    usuario = User.objects.create(username=f'{tipo}{n}')  # sem senha: evita o hash lento
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


def criar_turma(professor, **extra):
    modalidade = extra.pop('modalidade', None) or Modalidade.objects.get_or_create(nome='Pilates')[0]
    dados = dict(
        modalidade=modalidade, dia_semana=Turma.SEGUNDA, horario=time(8, 0),
        professor=professor, sala='Sala 1', capacidade_maxima=10,
    )
    dados.update(extra)
    return Turma.objects.create(**dados)


def dados_turma(professor, modalidade, **extra):
    dados = {
        'modalidade': modalidade.id, 'dia_semana': 'segunda', 'horario': '08:00',
        'professor': professor.id, 'sala': 'Sala 2', 'capacidade_maxima': 12,
    }
    dados.update(extra)
    return dados


class ModeloTurmaTests(TestCase):
    def test_professor_aponta_para_a_classe_user(self):
        # Bug antigo: ForeignKey(User(), ...) passava uma INSTÂNCIA em vez da classe.
        self.assertIs(Turma._meta.get_field('professor').related_model, User)

    def test_capacidade_zero_ou_negativa_e_invalida(self):
        for capacidade in (0, -3):
            turma = Turma(capacidade_maxima=capacidade)
            with self.assertRaises(ValidationError):
                turma.clean()

    def test_capacidade_positiva_e_valida(self):
        Turma(capacidade_maxima=1).clean()  # não levanta

    def test_str_mostra_modalidade_e_dia(self):
        turma = criar_turma(criar_usuario(Perfil.PROFESSOR))
        self.assertIn('Pilates', str(turma))
        self.assertIn('Segunda', str(turma))


class VisitanteTurmasTests(TestCase):
    """Sem login, toda tela de turmas manda para o login (não para o painel)."""

    def setUp(self):
        self.turma = criar_turma(criar_usuario(Perfil.PROFESSOR))

    def test_visitante_vai_para_o_login(self):
        urls = [
            reverse('listar_turmas'),
            reverse('criar_turma'),
            reverse('editar_turma', args=[self.turma.id]),
            reverse('desativar_turma', args=[self.turma.id]),
            reverse('criar_modalidade'),
        ]
        for url in urls:
            with self.subTest(url=url):
                resposta = self.client.get(url)
                self.assertRedirects(
                    resposta, f"{reverse('entrar')}?next={url}", fetch_redirect_response=False,
                )

    def test_visitante_nao_desativa_turma_por_post(self):
        url = reverse('desativar_turma', args=[self.turma.id])
        resposta = self.client.post(url)
        self.assertEqual(resposta.status_code, 302)
        self.turma.refresh_from_db()
        self.assertTrue(self.turma.ativo)


class PermissoesTurmasTests(TestCase):
    def setUp(self):
        self.professor = criar_usuario(Perfil.PROFESSOR)
        self.turma = criar_turma(self.professor)

    def _assert_barrado(self, usuario):
        self.client.force_login(usuario)
        for nome, args in (('criar_turma', []), ('editar_turma', [self.turma.id]),
                           ('criar_modalidade', [])):
            with self.subTest(usuario=usuario.perfil.tipo, rota=nome):
                resposta = self.client.get(reverse(nome, args=args))
                self.assertRedirects(resposta, reverse('painel'), fetch_redirect_response=False)
        resposta = self.client.post(reverse('desativar_turma', args=[self.turma.id]))
        self.assertRedirects(resposta, reverse('painel'), fetch_redirect_response=False)
        self.turma.refresh_from_db()
        self.assertTrue(self.turma.ativo)

    def test_professor_nao_cria_edita_nem_desativa(self):
        self._assert_barrado(self.professor)

    def test_aluna_nao_cria_edita_nem_desativa(self):
        self._assert_barrado(criar_usuario(Perfil.ALUNO))

    def test_aluna_nao_ve_a_lista_de_turmas(self):
        self.client.force_login(criar_usuario(Perfil.ALUNO))
        resposta = self.client.get(reverse('listar_turmas'))
        self.assertRedirects(resposta, reverse('painel'), fetch_redirect_response=False)

    def test_professor_ve_a_lista_de_turmas(self):
        self.client.force_login(self.professor)
        self.assertEqual(self.client.get(reverse('listar_turmas')).status_code, 200)


class ListarTurmasTests(TestCase):
    def setUp(self):
        self.prof_a = criar_usuario(Perfil.PROFESSOR)
        self.prof_b = criar_usuario(Perfil.PROFESSOR)
        self.turma_a = criar_turma(self.prof_a, sala='Sala A')
        self.turma_b = criar_turma(self.prof_b, sala='Sala B')
        self.inativa = criar_turma(self.prof_a, sala='Sala Inativa', ativo=False)

    def test_recepcao_ve_todas_as_turmas_ativas(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        turmas = set(self.client.get(reverse('listar_turmas')).context['turmas'])
        self.assertEqual(turmas, {self.turma_a, self.turma_b})

    def test_financeiro_ve_todas_as_turmas_ativas(self):
        self.client.force_login(criar_usuario(Perfil.FINANCEIRO))
        turmas = set(self.client.get(reverse('listar_turmas')).context['turmas'])
        self.assertEqual(turmas, {self.turma_a, self.turma_b})

    def test_professor_ve_so_as_proprias_turmas(self):
        self.client.force_login(self.prof_a)
        turmas = list(self.client.get(reverse('listar_turmas')).context['turmas'])
        self.assertEqual(turmas, [self.turma_a])

    def test_turma_desativada_nao_aparece(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        resposta = self.client.get(reverse('listar_turmas'))
        self.assertNotContains(resposta, 'Sala Inativa')

    def test_botao_desativar_e_um_formulario_post(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        resposta = self.client.get(reverse('listar_turmas'))
        url = reverse('desativar_turma', args=[self.turma_a.id])
        self.assertContains(resposta, f'action="{url}"')
        self.assertContains(resposta, 'name="csrfmiddlewaretoken"')

    def test_professor_nao_ve_botoes_de_edicao(self):
        self.client.force_login(self.prof_a)
        resposta = self.client.get(reverse('listar_turmas'))
        self.assertNotContains(resposta, reverse('desativar_turma', args=[self.turma_a.id]))


class CriarEditarTurmaTests(TestCase):
    def setUp(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        self.professor = criar_usuario(Perfil.PROFESSOR)
        self.modalidade = Modalidade.objects.create(nome='Yoga')

    def test_cria_turma_valida(self):
        resposta = self.client.post(
            reverse('criar_turma'), dados_turma(self.professor, self.modalidade),
        )
        self.assertRedirects(resposta, reverse('listar_turmas'))
        turma = Turma.objects.get()
        self.assertEqual(turma.sala, 'Sala 2')
        self.assertEqual(turma.professor, self.professor)
        self.assertTrue(turma.ativo)

    def test_capacidade_zero_nao_cria(self):
        resposta = self.client.post(
            reverse('criar_turma'),
            dados_turma(self.professor, self.modalidade, capacidade_maxima=0),
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Turma.objects.count(), 0)

    def test_so_professor_pode_ser_o_responsavel(self):
        aluna = criar_usuario(Perfil.ALUNO)
        resposta = self.client.post(
            reverse('criar_turma'), dados_turma(aluna, self.modalidade),
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Turma.objects.count(), 0)

    def test_edita_turma(self):
        turma = criar_turma(self.professor, modalidade=self.modalidade)
        resposta = self.client.post(
            reverse('editar_turma', args=[turma.id]),
            dados_turma(self.professor, self.modalidade, sala='Sala Nova', capacidade_maxima=20),
        )
        self.assertRedirects(resposta, reverse('listar_turmas'))
        turma.refresh_from_db()
        self.assertEqual(turma.sala, 'Sala Nova')
        self.assertEqual(turma.capacidade_maxima, 20)

    def test_editar_turma_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('editar_turma', args=[99999])).status_code, 404)


class DesativarTurmaTests(TestCase):
    def setUp(self):
        self.recepcao = criar_usuario(Perfil.RECEPCAO)
        self.client.force_login(self.recepcao)
        self.turma = criar_turma(criar_usuario(Perfil.PROFESSOR))
        self.url = reverse('desativar_turma', args=[self.turma.id])

    def test_get_nao_desativa(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 405)
        self.turma.refresh_from_db()
        self.assertTrue(self.turma.ativo)

    def test_post_desativa_mas_nao_apaga(self):
        resposta = self.client.post(self.url)
        self.assertRedirects(resposta, reverse('listar_turmas'))
        self.turma.refresh_from_db()
        self.assertFalse(self.turma.ativo)
        self.assertTrue(Turma.objects.filter(pk=self.turma.pk).exists())

    def test_post_sem_token_csrf_e_recusado(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.recepcao)
        resposta = cliente.post(self.url)
        self.assertEqual(resposta.status_code, 403)
        self.turma.refresh_from_db()
        self.assertTrue(self.turma.ativo)

    def test_desativar_turma_inexistente_da_404(self):
        resposta = self.client.post(reverse('desativar_turma', args=[99999]))
        self.assertEqual(resposta.status_code, 404)

    def test_mensagem_de_confirmacao_aparece_na_lista(self):
        resposta = self.client.post(self.url, follow=True)
        self.assertContains(resposta, 'Turma desativada.')


class ModalidadeTests(TestCase):
    def setUp(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))

    def test_cria_modalidade(self):
        resposta = self.client.post(
            reverse('criar_modalidade'), {'nome': 'Zumba', 'descricao': 'Dança'},
        )
        self.assertRedirects(resposta, reverse('listar_turmas'))
        self.assertTrue(Modalidade.objects.filter(nome='Zumba').exists())

    def test_nome_repetido_nao_cria(self):
        Modalidade.objects.create(nome='Zumba')
        resposta = self.client.post(reverse('criar_modalidade'), {'nome': 'Zumba', 'descricao': ''})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Modalidade.objects.filter(nome='Zumba').count(), 1)
