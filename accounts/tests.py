from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from accounts.models import Perfil
from accounts.forms import CadastroColaboradorForm


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
        """Impede o cadastro com username já existente no sistema."""
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

    def test_validacao_email_duplicado(self):
        """Impede o cadastro com e-mail já existente no sistema."""
        User.objects.create_user(username='outro_user', email='duplicado@shefit.com.br', password='123')

        dados = {
            'nome': 'Novo Colaborador',
            'username': 'novo_usuario',
            'email': 'duplicado@shefit.com.br',
            'senha_provisoria': 'senhaForte123',
            'tipo': Perfil.Tipo.FINANCEIRO,
        }
        form = CadastroColaboradorForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_validacao_senha_curta(self):
        """Exige senha provisória de no mínimo 6 caracteres."""
        dados = {
            'nome': 'Novo Colaborador',
            'username': 'novo_usuario',
            'email': 'novo@shefit.com.br',
            'senha_provisoria': '12345',
            'tipo': Perfil.Tipo.PROFESSOR,
        }
        form = CadastroColaboradorForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn('senha_provisoria', form.errors)


class PainelAdminViewTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin
        self.user_admin = User.objects.create_user(username='admin_boss', password='senha_admin123', first_name='Chefe')
        Perfil.objects.create(usuario=self.user_admin, tipo=Perfil.Tipo.ADMIN)

        # Recepção
        self.user_recepcao = User.objects.create_user(username='recepcao_user', password='senha12345')
        Perfil.objects.create(usuario=self.user_recepcao, tipo=Perfil.Tipo.RECEPCAO)

        # Professor
        self.user_professor = User.objects.create_user(username='prof_user', password='senha12345')
        Perfil.objects.create(usuario=self.user_professor, tipo=Perfil.Tipo.PROFESSOR)

        # Financeiro
        self.user_financeiro = User.objects.create_user(username='fin_user', password='senha12345')
        Perfil.objects.create(usuario=self.user_financeiro, tipo=Perfil.Tipo.FINANCEIRO)

    def test_usuario_anonimo_redirecionado(self):
        """Usuário não logado não pode acessar o painel admin e é redirecionado para o login."""
        url = reverse('painel_admin')
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/entrar/', resposta.url)

    def test_outros_perfis_bloqueados_no_painel_admin(self):
        """Colaboradores que não são Admin são bloqueados e redirecionados."""
        for user in [self.user_recepcao, self.user_professor, self.user_financeiro]:
            self.client.force_login(user)
            resposta = self.client.get(reverse('painel_admin'))
            self.assertEqual(resposta.status_code, 302)
            self.assertEqual(resposta.url, reverse('painel'))

    def test_admin_acessa_painel_admin_com_sucesso(self):
        """Admin acessa a rota do painel e visualiza o formulário, métricas e a listagem sem links para /admin."""
        self.client.force_login(self.user_admin)
        resposta = self.client.get(reverse('painel_admin'))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, 'accounts/painel_admin.html')
        self.assertContains(resposta, 'Painel Admin')
        self.assertContains(resposta, '+ Novo Usuário')
        self.assertContains(resposta, 'Total de Administradores')
        self.assertContains(resposta, 'Total de Recepcionistas')
        self.assertContains(resposta, 'Total de Professores')
        self.assertContains(resposta, 'Total de Financeiro')
        self.assertContains(resposta, 'Colaboradores e Usuários')
        self.assertContains(resposta, 'admin_boss')

        # Garante que não há nenhum link para o Django Admin nativo (/admin)
        self.assertNotContains(resposta, 'href="/admin"')
        self.assertNotContains(resposta, 'Django Admin')

    def test_admin_cadastra_novo_colaborador_com_sucesso(self):
        """Admin submete o formulário e registra um novo colaborador."""
        self.client.force_login(self.user_admin)

        dados_post = {
            'nome': 'Carla Recepção Nova',
            'username': 'carla.recepcao',
            'email': 'carla@shefit.com.br',
            'senha_provisoria': 'senhaSegura999',
            'tipo': Perfil.Tipo.RECEPCAO,
        }
        resposta = self.client.post(reverse('painel_admin'), data=dados_post, follow=True)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'cadastrado(a) com sucesso')

        # Verifica se o usuário e o perfil foram criados no banco
        novo_user = User.objects.get(username='carla.recepcao')
        self.assertEqual(novo_user.email, 'carla@shefit.com.br')
        self.assertEqual(novo_user.perfil.tipo, Perfil.Tipo.RECEPCAO)
        self.assertTrue(novo_user.check_password('senhaSegura999'))

    def test_admin_alterna_status_ativo_inativo_colaborador(self):
        """Admin desativa e depois reativa um colaborador via POST."""
        self.client.force_login(self.user_admin)
        url = reverse('alternar_status_usuario', args=[self.user_recepcao.id])

        # 1. Desativar
        resposta = self.client.post(url, follow=True)
        self.assertEqual(resposta.status_code, 200)
        self.user_recepcao.refresh_from_db()
        self.assertFalse(self.user_recepcao.is_active)
        self.assertContains(resposta, 'desativado com sucesso')

        # 2. Reativar
        resposta = self.client.post(url, follow=True)
        self.assertEqual(resposta.status_code, 200)
        self.user_recepcao.refresh_from_db()
        self.assertTrue(self.user_recepcao.is_active)
        self.assertContains(resposta, 'ativado com sucesso')

    def test_admin_nao_pode_desativar_a_si_mesmo(self):
        """Admin não pode desativar sua própria conta."""
        self.client.force_login(self.user_admin)
        url = reverse('alternar_status_usuario', args=[self.user_admin.id])

        resposta = self.client.post(url, follow=True)
        self.assertEqual(resposta.status_code, 200)
        self.user_admin.refresh_from_db()
        self.assertTrue(self.user_admin.is_active)
        self.assertContains(resposta, 'Não é permitido desativar a sua própria conta')

    def test_redirecionamento_rota_painel_para_admin(self):
        """Admin ao acessar a rota genérica /painel/ é redirecionado para /painel/admin/."""
        self.client.force_login(self.user_admin)
        resposta = self.client.get(reverse('painel'))
        self.assertRedirects(resposta, reverse('painel_admin'))

