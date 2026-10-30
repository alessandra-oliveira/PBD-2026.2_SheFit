from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Perfil
from .forms import MatriculaForm
from .models import Aluno, Anamnese


def dados_aluno(**extra):
    dados = {
        'nome': 'Maria Souza', 'cpf': '12345678901',
        'data_nascimento': '2000-05-10', 'endereco': 'Rua A, 1',
        'telefone': '81999990000', 'email': 'maria@exemplo.com',
        'contato_emergencia_nome': 'João Souza',
        'contato_emergencia_telefone': '81988887777',
        'username': 'maria', 'password': 'Senha!Forte123',
    }
    dados.update(extra)
    return dados


class BaseRecepcaoTestCase(TestCase):
    def setUp(self):
        usuario = User.objects.create_user(username='recep', password='senha12345')
        Perfil.objects.create(usuario=usuario, tipo=Perfil.RECEPCAO)
        self.client.login(username='recep', password='senha12345')


class CadastrarAlunoTests(BaseRecepcaoTestCase):
    def test_cadastro_cria_user_perfil_e_aluno(self):
        resposta = self.client.post(reverse('cadastrar_aluno'), dados_aluno())

        aluno = Aluno.objects.get(cpf='12345678901')
        self.assertRedirects(resposta, reverse('preencher_anamnese', args=[aluno.id]))
        self.assertEqual(aluno.perfil.tipo, Perfil.ALUNO)
        self.assertEqual(aluno.perfil.usuario.username, 'maria')

    def test_senha_digitada_vira_a_senha_de_login_do_aluno(self):
        self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        self.assertTrue(self.client.login(username='maria', password='Senha!Forte123'))

    def test_aluno_nasce_inativo_ate_a_anamnese(self):
        self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        self.assertFalse(Aluno.objects.get(cpf='12345678901').ativo)

    def test_cpf_duplicado_nao_cria_nada(self):
        self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        users_antes = User.objects.count()
        resposta = self.client.post(reverse('cadastrar_aluno'), dados_aluno(
            username='outra', email='outra@exemplo.com', telefone='81977770000',
        ))
        self.assertEqual(resposta.status_code, 200)  # reexibe o formulário com erro
        self.assertEqual(Aluno.objects.count(), 1)
        self.assertEqual(User.objects.count(), users_antes)  # nenhum User órfão

    def test_usuario_ja_em_uso_e_rejeitado(self):
        User.objects.create_user(username='maria', password='x')
        resposta = self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Aluno.objects.count(), 0)


class EditarAlunoTests(BaseRecepcaoTestCase):
    def setUp(self):
        super().setUp()
        self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        self.aluno = Aluno.objects.get(cpf='12345678901')

    def test_formulario_de_edicao_nao_pede_usuario_nem_senha(self):
        resposta = self.client.get(reverse('editar_aluno', args=[self.aluno.id]))
        self.assertNotIn('username', resposta.context['form'].fields)
        self.assertNotIn('password', resposta.context['form'].fields)

    def test_data_de_nascimento_aparece_preenchida_na_edicao(self):
        resposta = self.client.get(reverse('editar_aluno', args=[self.aluno.id]))
        # <input type="date"> só exibe o valor em AAAA-MM-DD
        self.assertContains(resposta, 'value="2000-05-10"')

    def test_editar_mantendo_cpf_email_e_telefone_funciona(self):
        dados = dados_aluno(nome='Maria S. Souza', endereco='Rua B, 2')
        dados.pop('username'); dados.pop('password')
        resposta = self.client.post(reverse('editar_aluno', args=[self.aluno.id]), dados)

        self.assertRedirects(resposta, reverse('painel_recepcao'))
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.nome, 'Maria S. Souza')
        self.assertEqual(self.aluno.endereco, 'Rua B, 2')

    def test_editar_nao_cria_outro_user_nem_perfil(self):
        dados = dados_aluno(nome='Novo Nome')
        dados.pop('username'); dados.pop('password')
        self.client.post(reverse('editar_aluno', args=[self.aluno.id]), dados)
        self.assertEqual(Perfil.objects.filter(tipo=Perfil.ALUNO).count(), 1)

    def test_editar_para_cpf_de_outro_aluno_continua_bloqueado(self):
        self.client.post(reverse('cadastrar_aluno'), dados_aluno(
            cpf='99999999999', username='ana', email='ana@exemplo.com',
            telefone='81966660000',
        ))
        dados = dados_aluno(cpf='99999999999')
        dados.pop('username'); dados.pop('password')
        resposta = self.client.post(reverse('editar_aluno', args=[self.aluno.id]), dados)
        self.assertEqual(resposta.status_code, 200)
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.cpf, '12345678901')


class PreencherAnamneseTests(BaseRecepcaoTestCase):
    def setUp(self):
        super().setUp()
        self.client.post(reverse('cadastrar_aluno'), dados_aluno())
        self.aluno = Aluno.objects.get(cpf='12345678901')
        self.url = reverse('preencher_anamnese', args=[self.aluno.id])

    def test_sem_marcar_a_autorizacao_nada_e_salvo_e_o_aluno_continua_inativo(self):
        resposta = self.client.post(self.url, {
            'restricoes_medicas': 'Asma', 'historico_lesoes': '', 'condicoes_cronicas': '',
        })
        self.assertEqual(resposta.status_code, 200)  # reexibe o formulário com erro
        self.assertFalse(Anamnese.objects.filter(aluno=self.aluno).exists())
        self.aluno.refresh_from_db()
        self.assertFalse(self.aluno.ativo)

    def test_marcando_a_autorizacao_salva_e_ativa_o_aluno(self):
        resposta = self.client.post(self.url, {
            'restricoes_medicas': 'Asma', 'historico_lesoes': '', 'condicoes_cronicas': '',
            'autorizacao_atividade_fisica': 'on',
        })
        # A recepção volta ao PRÓPRIO painel (a consulta é exclusiva do professor)
        self.assertRedirects(resposta, reverse('painel_recepcao'))
        self.aluno.refresh_from_db()
        self.assertTrue(self.aluno.ativo)
        self.assertTrue(self.aluno.anamnese.autorizacao_atividade_fisica)
        self.assertEqual(self.aluno.anamnese.restricoes_medicas, 'Asma')

    def test_recepcao_nao_e_mandada_para_tela_de_outro_perfil_ao_salvar(self):
        resposta = self.client.post(self.url, {'autorizacao_atividade_fisica': 'on'}, follow=True)
        textos = [str(m) for m in resposta.context['messages']]
        self.assertFalse(any('permissão' in t for t in textos))
        self.assertEqual(resposta.status_code, 200)

    def test_campos_de_texto_sao_opcionais(self):
        resposta = self.client.post(self.url, {'autorizacao_atividade_fisica': 'on'})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Anamnese.objects.filter(aluno=self.aluno).exists())


class ListaDeAlunosNaMatriculaTests(BaseRecepcaoTestCase):
    def _aluno(self, n, ativo=True, anamnese=None):
        """anamnese: None = sem ficha; True/False = ficha com essa autorização."""
        usuario = User.objects.create_user(username=f'u{n}', password='senha12345')
        perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.ALUNO)
        aluno = Aluno.objects.create(
            perfil=perfil, nome=f'Aluna {n}', cpf=f'{n:011d}',
            data_nascimento=date(2000, 1, 1), endereco='Rua A, 1',
            telefone=f'8199{n:07d}', email=f'a{n}@exemplo.com',
            contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
            ativo=ativo,
        )
        if anamnese is not None:
            Anamnese.objects.create(aluno=aluno, autorizacao_atividade_fisica=anamnese)
        return aluno

    def test_so_lista_alunos_aptos_para_matricula(self):
        apta = self._aluno(1, ativo=True, anamnese=True)
        self._aluno(2, ativo=True, anamnese=None)      # sem anamnese
        self._aluno(3, ativo=True, anamnese=False)     # sem autorização
        self._aluno(4, ativo=False, anamnese=True)     # desativada

        listados = list(MatriculaForm().fields['aluno'].queryset)
        self.assertEqual(listados, [apta])