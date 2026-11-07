from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno, Anamnese
from financeiro.models import Plano
from financeiro.servicos import realizar_matricula
from .models import Frequencia
from .servicos import (
    JANELA_ENTRADA_DUPLICADA, LIMITE_RESULTADOS_BUSCA, avaliar_acesso,
    buscar_alunos, processar_entrada_aluno, registrar_entrada,
)

_seq = count(1)


def criar_usuario(tipo):
    n = next(_seq)
    usuario = User.objects.create(username=f'u{n}')  # sem senha: evita o hash lento
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


def criar_aluna(nome, cpf=None, ativo=True, com_matricula=True):
    """Aluna com anamnese autorizada. Com matrícula iniciada hoje, o acesso fica liberado."""
    n = next(_seq)
    perfil = Perfil.objects.create(usuario=User.objects.create(username=f'a{n}'), tipo=Perfil.ALUNO)
    aluno = Aluno.objects.create(
        perfil=perfil, nome=nome, cpf=cpf or f'{n:011d}',
        data_nascimento=date(2000, 1, 1), endereco='Rua A, 1',
        telefone=f'8199{n:07d}', email=f'a{n}@exemplo.com',
        contato_emergencia_nome='Contato', contato_emergencia_telefone='81988887777',
    )
    Anamnese.objects.create(aluno=aluno, autorizacao_atividade_fisica=True)
    if com_matricula:
        plano, _ = Plano.objects.get_or_create(
            nome='Mensal',
            defaults=dict(periodicidade='mensal', valor=Decimal('100.00'),
                          taxa_adesao=Decimal('0.00'), dia_vencimento=10),
        )
        realizar_matricula(aluno, plano, timezone.localdate(), 'pix')
    if not ativo:
        aluno.ativo = False
        aluno.save()
    return aluno


class BuscarAlunosTests(TestCase):
    def test_cpf_com_ou_sem_pontuacao_acha_a_aluna(self):
        ana = criar_aluna('Ana Lima', cpf='12345678901', com_matricula=False)
        for termo in ('12345678901', '123.456.789-01'):
            alunos, truncado = buscar_alunos(termo)
            self.assertEqual(alunos, [ana])
            self.assertFalse(truncado)

    def test_nome_parcial_devolve_todas_e_nao_so_a_primeira(self):
        a = criar_aluna('Maria Silva', com_matricula=False)
        b = criar_aluna('Maria Souza', com_matricula=False)
        criar_aluna('Joana Prado', com_matricula=False)
        alunos, _ = buscar_alunos('maria')
        self.assertEqual(set(alunos), {a, b})

    def test_termo_vazio_nao_devolve_ninguem(self):
        criar_aluna('Ana Lima', com_matricula=False)
        self.assertEqual(buscar_alunos('   '), ([], False))
        self.assertEqual(buscar_alunos(None), ([], False))

    def test_busca_por_nome_respeita_o_limite_e_avisa_que_truncou(self):
        for i in range(LIMITE_RESULTADOS_BUSCA + 2):
            criar_aluna(f'Turma Teste {i:02d}', com_matricula=False)
        alunos, truncado = buscar_alunos('turma teste')
        self.assertEqual(len(alunos), LIMITE_RESULTADOS_BUSCA)
        self.assertTrue(truncado)

    def test_aluna_inativa_tambem_e_encontrada(self):
        inativa = criar_aluna('Ana Lima', ativo=False, com_matricula=False)
        self.assertEqual(buscar_alunos('ana')[0], [inativa])


class AvaliarAcessoTests(TestCase):
    def test_aluna_em_dia_e_liberada_e_a_consulta_nao_grava_entrada(self):
        aluna = criar_aluna('Ana Lima')
        resultado = avaliar_acesso(aluna)
        self.assertTrue(resultado['sucesso'])
        self.assertEqual(resultado['status'], 'liberado')
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_aluna_inativa_e_bloqueada_mesmo_com_matricula_em_dia(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resultado = avaliar_acesso(aluna)
        self.assertFalse(resultado['sucesso'])
        self.assertEqual(resultado['status'], 'bloqueado')

    def test_aluna_sem_matricula_e_bloqueada(self):
        aluna = criar_aluna('Ana Lima', com_matricula=False)
        self.assertFalse(avaliar_acesso(aluna)['sucesso'])


class RegistrarEntradaTests(TestCase):
    def test_acesso_liberado_registra_uma_entrada(self):
        aluna = criar_aluna('Ana Lima')
        resultado = registrar_entrada(aluna)
        self.assertTrue(resultado['registrada'])
        self.assertFalse(resultado['duplicada'])
        self.assertEqual(Frequencia.objects.filter(aluno=aluna, liberado=True).count(), 1)

    def test_repetir_logo_em_seguida_nao_duplica(self):
        aluna = criar_aluna('Ana Lima')
        registrar_entrada(aluna)
        segunda = registrar_entrada(aluna)
        self.assertFalse(segunda['registrada'])
        self.assertTrue(segunda['duplicada'])
        self.assertEqual(Frequencia.objects.count(), 1)

    def test_passada_a_janela_uma_nova_entrada_e_aceita(self):
        aluna = criar_aluna('Ana Lima')
        registrar_entrada(aluna)
        Frequencia.objects.update(
            data_hora=timezone.now() - JANELA_ENTRADA_DUPLICADA - timedelta(minutes=1),
        )
        resultado = registrar_entrada(aluna)
        self.assertTrue(resultado['registrada'])
        self.assertEqual(Frequencia.objects.count(), 2)

    def test_acesso_bloqueado_nao_registra_nada(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resultado = registrar_entrada(aluna)
        self.assertFalse(resultado['registrada'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_entrada_de_uma_aluna_nao_bloqueia_a_de_outra(self):
        registrar_entrada(criar_aluna('Ana Lima'))
        registrar_entrada(criar_aluna('Bia Souza'))
        self.assertEqual(Frequencia.objects.count(), 2)


class ProcessarEntradaAlunoTests(TestCase):
    def test_um_resultado_registra_a_entrada(self):
        aluna = criar_aluna('Ana Lima', cpf='12345678901')
        resultado = processar_entrada_aluno('12345678901')
        self.assertTrue(resultado['sucesso'])
        self.assertEqual(Frequencia.objects.filter(aluno=aluna).count(), 1)

    def test_nome_ambiguo_nao_registra_ninguem(self):
        criar_aluna('Maria Silva')
        criar_aluna('Maria Souza')
        resultado = processar_entrada_aluno('maria')
        self.assertFalse(resultado['sucesso'])
        self.assertEqual(len(resultado['candidatos']), 2)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_nao_encontrada(self):
        resultado = processar_entrada_aluno('zzzz')
        self.assertFalse(resultado['sucesso'])
        self.assertIsNone(resultado['aluno'])


class TelaEntradaViewTests(TestCase):
    def setUp(self):
        self.client.force_login(criar_usuario(Perfil.RECEPCAO))
        self.url = reverse('tela_entrada_recepcao')

    def test_buscar_so_consulta_e_nao_registra_entrada(self):
        aluna = criar_aluna('Ana Lima', cpf='12345678901')
        resposta = self.client.get(self.url, {'q': aluna.cpf})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context['resultado']['sucesso'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_recarregar_a_pagina_nao_cria_entradas(self):
        aluna = criar_aluna('Ana Lima', cpf='12345678901')
        for _ in range(3):
            self.client.get(self.url, {'q': aluna.cpf})
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_nome_ambiguo_lista_as_candidatas_sem_escolher_ninguem(self):
        criar_aluna('Maria Silva')
        criar_aluna('Maria Souza')
        resposta = self.client.get(self.url, {'q': 'maria'})
        self.assertIsNone(resposta.context['resultado'])
        self.assertEqual(len(resposta.context['candidatos']), 2)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_escolher_uma_candidata_mostra_a_situacao_dela(self):
        criar_aluna('Maria Silva')
        souza = criar_aluna('Maria Souza')
        resposta = self.client.get(self.url, {'q': 'maria', 'aluno': souza.id})
        self.assertEqual(resposta.context['resultado']['aluno'], souza)

    def test_aluna_nao_encontrada(self):
        resposta = self.client.get(self.url, {'q': 'zzzz'})
        self.assertTrue(resposta.context['nao_encontrado'])
        self.assertIsNone(resposta.context['resultado'])

    def test_aluna_inativa_aparece_como_bloqueada(self):
        criar_aluna('Ana Lima', cpf='12345678901', ativo=False)
        resposta = self.client.get(self.url, {'q': '12345678901'})
        self.assertFalse(resposta.context['resultado']['sucesso'])
        self.assertContains(resposta, 'Acesso Bloqueado')
        self.assertNotContains(resposta, 'Registrar entrada')

    def test_aluna_liberada_mostra_o_botao_de_registrar(self):
        criar_aluna('Ana Lima', cpf='12345678901')
        resposta = self.client.get(self.url, {'q': '12345678901'})
        self.assertContains(resposta, 'Registrar entrada')

    def test_tela_nao_mostra_marcadores_de_citacao(self):
        criar_aluna('Ana Lima', cpf='12345678901')
        resposta = self.client.get(self.url, {'q': '12345678901'})
        self.assertNotContains(resposta, '[cite')

    def test_post_registra_a_entrada_e_volta_para_a_tela(self):
        aluna = criar_aluna('Ana Lima')
        resposta = self.client.post(self.url, {'aluno_id': aluna.id})
        self.assertRedirects(resposta, self.url, fetch_redirect_response=False)
        self.assertEqual(Frequencia.objects.filter(aluno=aluna).count(), 1)

    def test_post_repetido_nao_duplica(self):
        aluna = criar_aluna('Ana Lima')
        self.client.post(self.url, {'aluno_id': aluna.id})
        self.client.post(self.url, {'aluno_id': aluna.id})
        self.assertEqual(Frequencia.objects.count(), 1)

    def test_post_de_aluna_bloqueada_nao_registra_e_avisa(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resposta = self.client.post(self.url, {'aluno_id': aluna.id}, follow=True)
        self.assertEqual(Frequencia.objects.count(), 0)
        textos = [str(m) for m in resposta.context['messages']]
        self.assertTrue(any('bloqueado' in t.lower() for t in textos))

    def test_post_com_id_invalido_nao_quebra(self):
        for dados in ({'aluno_id': 'abc'}, {'aluno_id': '99999'}, {}):
            resposta = self.client.post(self.url, dados)
            self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_perfil_financeiro_nao_acessa_a_tela_nem_registra(self):
        aluna = criar_aluna('Ana Lima')
        self.client.force_login(criar_usuario(Perfil.FINANCEIRO))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {'aluno_id': aluna.id}).status_code, 302)
        self.assertEqual(Frequencia.objects.count(), 0)
