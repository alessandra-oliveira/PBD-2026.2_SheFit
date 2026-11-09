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
        resposta_gestao = self.client.get(reverse('gestao_estudantes'))
        self.assertContains(resposta_gestao, 'Ana Lima')
        self.assertContains(resposta_gestao, 'Bia Souza')

    def test_tem_o_botao_de_novo_cadastro(self):
        resposta = self.client.get(reverse('painel_recepcao'))
        self.assertContains(resposta, reverse('cadastrar_aluno'))


class AdminPerfilModelTests(TestCase):
    def test_opcoes_perfil_incluem_papeis_necessarios(self):
        """Verifica se os papéis Admin, Recepcao, Professor, Financeiro e Aluno estão disponíveis."""
        self.assertEqual(Perfil.Tipo.ADMIN, 'admin')
        self.assertEqual(Perfil.Tipo.RECEPCAO, 'recepcao')
        self.assertEqual(Perfil.Tipo.PROFESSOR, 'professor')
        self.assertEqual(Perfil.Tipo.FINANCEIRO, 'financeiro')
        self.assertEqual(Perfil.Tipo.ALUNO, 'aluno')

        # Compatibilidade com constantes de classe
        self.assertEqual(Perfil.ADMIN, 'admin')
        self.assertEqual(Perfil.RECEPCAO, 'recepcao')
        self.assertEqual(Perfil.PROFESSOR, 'professor')
        self.assertEqual(Perfil.FINANCEIRO, 'financeiro')
        self.assertEqual(Perfil.ALUNO, 'aluno')

    def test_criacao_perfil_admin(self):
        """Cria um usuário com perfil de Administrador e valida propriedades."""
        usuario = User.objects.create_user(username='admin_test', password='senha_teste123')
        perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.Tipo.ADMIN)

        self.assertTrue(perfil.is_admin)
        self.assertFalse(perfil.is_recepcao)
        self.assertFalse(perfil.is_professor)
        self.assertFalse(perfil.is_financeiro)
        self.assertIn('Administrador', str(perfil))


class CadastroColaboradorFormTests(TestCase):
    def test_formulario_valido_cria_colaborador_e_perfil(self):
        """Testa o cadastro bem-sucedido de colaboradores com diferentes papéis."""
        from accounts.forms import CadastroColaboradorForm

        for papel in [Perfil.Tipo.RECEPCAO, Perfil.Tipo.PROFESSOR, Perfil.Tipo.FINANCEIRO]:
            dados = {
                'nome': f'Colaborador {papel}',
                'username': f'usuario_{papel}',
                'email': f'{papel}@shefit.com.br',
                'senha_provisoria': 'senhaForte123',
                'tipo': papel,
            }
            form = CadastroColaboradorForm(data=dados)
            self.assertTrue(form.is_valid(), f"Formulário deveria ser válido para {papel}: {form.errors}")

            usuario_criado = form.save()
            self.assertEqual(usuario_criado.username, f'usuario_{papel}')
            self.assertEqual(usuario_criado.first_name, 'Colaborador')
            self.assertEqual(usuario_criado.last_name, papel)
            self.assertEqual(usuario_criado.email, f'{papel}@shefit.com.br')
            self.assertTrue(hasattr(usuario_criado, 'perfil'))
            self.assertEqual(usuario_criado.perfil.tipo, papel)

    def test_validacao_username_duplicado(self):
        from accounts.forms import CadastroColaboradorForm

        User.objects.create_user(username='colaborador1', email='outro@shefit.com.br', password='123')
        dados = {
            'nome': 'Novo Colaborador',
            'username': 'colaborador1',
            'email': 'novo@shefit.com.br',
            'senha_provisoria': 'senhaForte123',
            'tipo': Perfil.Tipo.RECEPCAO,
        }
        form = CadastroColaboradorForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)


class PainelAdminViewTests(TestCase):
    def setUp(self):
        self.user_admin = User.objects.create_user(username='admin_boss', password='senha_admin123', first_name='Chefe')
        Perfil.objects.create(usuario=self.user_admin, tipo=Perfil.Tipo.ADMIN)

        self.user_recepcao = User.objects.create_user(username='recepcao_user', password='senha12345')
        Perfil.objects.create(usuario=self.user_recepcao, tipo=Perfil.Tipo.RECEPCAO)

    def test_admin_acessa_painel_admin_com_sucesso(self):
        self.client.force_login(self.user_admin)
        resposta = self.client.get(reverse('painel_admin'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Painel do Administrador')
        self.assertContains(resposta, '+ Novo Usuário')
        self.assertContains(resposta, 'Total de Administradores')
        self.assertNotContains(resposta, 'href="/admin"')
        self.assertNotContains(resposta, 'Django Admin')

    def test_admin_alterna_status_ativo_inativo_colaborador(self):
        self.client.force_login(self.user_admin)
        url = reverse('alternar_status_usuario', args=[self.user_recepcao.id])
        resposta = self.client.post(url, follow=True)
        self.assertEqual(resposta.status_code, 200)
        self.user_recepcao.refresh_from_db()
        self.assertFalse(self.user_recepcao.is_active)
        self.assertContains(resposta, 'desativado com sucesso')

