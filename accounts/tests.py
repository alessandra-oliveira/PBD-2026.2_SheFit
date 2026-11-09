from datetime import date
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from alunos.models import Aluno
from .models import Perfil

_seq = count(1)

PAINEL_DE = {
    Perfil.ALUNO: 'painel_aluno',
    Perfil.PROFESSOR: 'painel_professor',
    Perfil.RECEPCAO: 'painel_recepcao',
    Perfil.FINANCEIRO: 'painel_financeiro',
}


def criar_usuario(tipo, password=None):
    n = next(_seq)
    usuario = User.objects.create(username=f'{tipo}{n}')
    if password:
        usuario.set_password(password)
        usuario.save()
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


class EntrarTests(TestCase):
    def setUp(self):
        self.usuario = criar_usuario(Perfil.RECEPCAO, password='senha12345')
        self.url = reverse('entrar')

    def test_tela_de_login_abre(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_login_correto_vai_para_o_painel_e_cria_sessao(self):
        resposta = self.client.post(
            self.url, {'username': self.usuario.username, 'password': 'senha12345'},
        )
        self.assertRedirects(resposta, reverse('painel'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.id)

    def test_senha_errada_mostra_erro_e_nao_cria_sessao(self):
        resposta = self.client.post(
            self.url, {'username': self.usuario.username, 'password': 'errada'},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('inválidos', resposta.context['erro'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_usuario_inexistente_recebe_o_mesmo_erro_generico(self):
        errada = self.client.post(
            self.url, {'username': self.usuario.username, 'password': 'errada'},
        ).context['erro']
        inexistente = self.client.post(
            self.url, {'username': 'ninguem', 'password': 'qualquer'},
        ).context['erro']
        self.assertEqual(errada, inexistente)  # não revela se o usuário existe

    def test_usuario_sem_perfil_nao_entra(self):
        User.objects.create_user(username='semperfil', password='senha12345')
        resposta = self.client.post(self.url, {'username': 'semperfil', 'password': 'senha12345'})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('perfil', resposta.context['erro'].lower())
        self.assertNotIn('_auth_user_id', self.client.session)


class SairTests(TestCase):
    def test_sair_encerra_a_sessao_e_volta_ao_login(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        resposta = self.client.get(reverse('sair'))
        self.assertRedirects(resposta, reverse('entrar'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class PainelTests(TestCase):
    def test_cada_perfil_e_levado_ao_seu_painel(self):
        for tipo, rota in PAINEL_DE.items():
            with self.subTest(tipo=tipo):
                self.client.force_login(criar_usuario(tipo))
                resposta = self.client.get(reverse('painel'))
                self.assertRedirects(resposta, reverse(rota), fetch_redirect_response=False)

    def test_cada_painel_abre_para_o_perfil_certo(self):
        for tipo, rota in PAINEL_DE.items():
            with self.subTest(tipo=tipo):
                self.client.force_login(criar_usuario(tipo))
                self.assertEqual(self.client.get(reverse(rota)).status_code, 200)

    def test_cada_painel_barra_os_outros_perfis(self):
        for tipo in PAINEL_DE:
            self.client.force_login(criar_usuario(tipo))
            for outro_tipo, rota in PAINEL_DE.items():
                if outro_tipo == tipo:
                    continue
                with self.subTest(usuario=tipo, painel=rota):
                    self.assertEqual(self.client.get(reverse(rota)).status_code, 403)

    def test_visitante_vai_para_o_login(self):
        for rota in ['painel', *PAINEL_DE.values()]:
            with self.subTest(rota=rota):
                url = reverse(rota)
                resposta = self.client.get(url)
                self.assertRedirects(
                    resposta, f"{reverse('entrar')}?next={url}", fetch_redirect_response=False,
                )

    def test_usuario_sem_perfil_toma_403_e_nao_erro_500(self):
        # Ex.: o superusuário do admin não tem Perfil. Antes dava AttributeError (500).
        self.client.force_login(User.objects.create_superuser('admin', password='senha12345'))
        for rota in ['painel', *PAINEL_DE.values()]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(reverse(rota)).status_code, 403)


class PainelRecepcaoTests(TestCase):
    def _aluna(self, nome):
        n = next(_seq)
        perfil = Perfil.objects.create(
            usuario=User.objects.create(username=f'aluna{n}'), tipo=Perfil.ALUNO,
        )
        return Aluno.objects.create(
            perfil=perfil, nome=nome, cpf=f'{n:011d}', data_nascimento=date(2000, 1, 1),
            endereco='Rua A, 1', telefone=f'8199{n:07d}', email=f'a{n}@exemplo.com',
            contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
        )

    def setUp(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))

    def test_lista_as_alunas_e_o_total(self):
        self._aluna('Ana Lima')
        self._aluna('Bia Souza')
        resposta = self.client.get(reverse('painel_recepcao'))
        self.assertEqual(resposta.context['total_alunos'], 2)
        self.assertContains(resposta, 'Ana Lima')
        self.assertContains(resposta, 'Bia Souza')

    def test_tem_o_botao_de_novo_cadastro(self):
        resposta = self.client.get(reverse('painel_recepcao'))
        self.assertContains(resposta, reverse('cadastrar_aluno'))
