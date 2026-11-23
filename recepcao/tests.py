from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Perfil
from alunos.models import Aluno, Anamnese
from financeiro.models import Cobranca, Matricula, Pagamento, Plano
from financeiro.servicos import realizar_matricula
from .models import Frequencia
from .servicos import (
    JANELA_ENTRADA_DUPLICADA, LIMITE_RESULTADOS_BUSCA, avaliar_acesso,
    buscar_alunos, liberar_excepcionalmente, processar_entrada_aluno,
    registrar_entrada,
)

_seq = count(1)


def criar_usuario(tipo):
    n = next(_seq)
    usuario = User.objects.create(username=f'u{n}')
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

class LiberarExcepcionalmenteServicoTests(TestCase):
    def setUp(self):
        self.usuario = criar_usuario(Perfil.RECEPCAO)

    def test_libera_aluna_bloqueada_e_grava_frequencia_excepcional(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resultado = liberar_excepcionalmente(aluna, 'Vai pagar agora no caixa', self.usuario)
        self.assertTrue(resultado['registrada'])
        self.assertIsNone(resultado['erro'])
        frequencia = Frequencia.objects.get()
        self.assertEqual(frequencia.aluno, aluna)
        self.assertTrue(frequencia.liberado)
        self.assertTrue(frequencia.excepcional)
        self.assertEqual(frequencia.motivo_excepcional, 'Vai pagar agora no caixa')
        self.assertEqual(frequencia.liberado_por, self.usuario)

    def test_motivo_vazio_ou_so_espacos_e_recusado(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        for motivo in ('', '   ', None):
            resultado = liberar_excepcionalmente(aluna, motivo, self.usuario)
            self.assertFalse(resultado['registrada'])
            self.assertTrue(resultado['erro'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_motivo_maior_que_255_caracteres_e_recusado(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resultado = liberar_excepcionalmente(aluna, 'x' * 256, self.usuario)
        self.assertFalse(resultado['registrada'])
        self.assertTrue(resultado['erro'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_sem_responsavel_a_liberacao_e_recusada(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resultado = liberar_excepcionalmente(aluna, 'Vai pagar hoje', None)
        self.assertFalse(resultado['registrada'])
        self.assertTrue(resultado['erro'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_aluna_com_acesso_liberado_nao_gera_liberacao_excepcional(self):
        aluna = criar_aluna('Ana Lima')
        resultado = liberar_excepcionalmente(aluna, 'Vai pagar hoje', self.usuario)
        self.assertFalse(resultado['registrada'])
        self.assertTrue(resultado['erro'])
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_nao_altera_matricula_nem_cobranca(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        matricula = Matricula.objects.get(aluno=aluna)
        situacao_antes = matricula.situacao
        campos = ('id', 'valor', 'paga', 'cancelada', 'vencimento')
        cobrancas_antes = list(Cobranca.objects.order_by('id').values(*campos))
        self.assertTrue(cobrancas_antes)

        liberar_excepcionalmente(aluna, 'Vai pagar agora no caixa', self.usuario)

        matricula = Matricula.objects.get(pk=matricula.pk)
        self.assertEqual(matricula.situacao, situacao_antes)
        self.assertEqual(
            list(Cobranca.objects.order_by('id').values(*campos)), cobrancas_antes,
        )
        self.assertEqual(Pagamento.objects.count(), 0)

    def test_repetir_logo_em_seguida_nao_duplica(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        liberar_excepcionalmente(aluna, 'Vai pagar hoje', self.usuario)
        segunda = liberar_excepcionalmente(aluna, 'Vai pagar hoje', self.usuario)
        self.assertFalse(segunda['registrada'])
        self.assertTrue(segunda['duplicada'])
        self.assertEqual(Frequencia.objects.count(), 1)

    def test_entrada_normal_nao_e_marcada_como_excepcional(self):
        aluna = criar_aluna('Ana Lima')
        registrar_entrada(aluna)
        frequencia = Frequencia.objects.get()
        self.assertFalse(frequencia.excepcional)
        self.assertEqual(frequencia.motivo_excepcional, '')
        self.assertIsNone(frequencia.liberado_por)


class LiberarExcepcionalViewTests(TestCase):
    def setUp(self):
        self.usuario = criar_usuario(Perfil.RECEPCAO)
        self.client.force_login(self.usuario)
        self.url = reverse('liberar_excepcional_recepcao')
        self.tela = reverse('tela_entrada_recepcao')

    def test_post_com_motivo_libera_e_volta_para_a_tela(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resposta = self.client.post(
            self.url, {'aluno_id': aluna.id, 'motivo': 'Vai pagar agora no caixa'},
        )
        self.assertRedirects(resposta, self.tela, fetch_redirect_response=False)
        frequencia = Frequencia.objects.get()
        self.assertTrue(frequencia.excepcional)
        self.assertEqual(frequencia.liberado_por, self.usuario)

    def test_post_sem_motivo_nao_grava_e_volta_para_a_mesma_aluna(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        resposta = self.client.post(self.url, {'aluno_id': aluna.id, 'motivo': '   '})
        self.assertRedirects(
            resposta, f'{self.tela}?aluno={aluna.pk}', fetch_redirect_response=False,
        )
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_get_nao_libera_nada(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_aluna_com_acesso_liberado_nao_recebe_liberacao_excepcional(self):
        aluna = criar_aluna('Ana Lima')
        self.client.post(self.url, {'aluno_id': aluna.id, 'motivo': 'Vai pagar hoje'})
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_post_com_id_invalido_nao_quebra(self):
        for dados in ({'aluno_id': 'abc'}, {'aluno_id': '99999'}, {}):
            resposta = self.client.post(self.url, dados)
            self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_perfil_financeiro_nao_libera(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        self.client.force_login(criar_usuario(Perfil.FINANCEIRO))
        resposta = self.client.post(
            self.url, {'aluno_id': aluna.id, 'motivo': 'Vai pagar hoje'},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Frequencia.objects.count(), 0)

    def test_botao_so_aparece_quando_o_acesso_esta_bloqueado(self):
        criar_aluna('Bia Souza', cpf='11111111111', ativo=False)
        criar_aluna('Ana Lima', cpf='22222222222')
        bloqueada = self.client.get(self.tela, {'q': '11111111111'})
        liberada = self.client.get(self.tela, {'q': '22222222222'})
        self.assertContains(bloqueada, 'Liberar excepcionalmente')
        self.assertNotContains(liberada, 'Liberar excepcionalmente')

    def test_tela_mostra_a_liberacao_feita_hoje(self):
        aluna = criar_aluna('Ana Lima', cpf='12345678901', ativo=False)
        liberar_excepcionalmente(aluna, 'Vai pagar agora no caixa', self.usuario)
        resposta = self.client.get(self.tela, {'q': '12345678901'})
        self.assertIsNotNone(resposta.context['liberacao_hoje'])
        self.assertContains(resposta, 'Vai pagar agora no caixa')


class HistoricoLiberacoesViewTests(TestCase):
    def setUp(self):
        self.usuario = criar_usuario(Perfil.RECEPCAO)
        self.client.force_login(self.usuario)
        self.url = reverse('historico_liberacoes')

    def test_lista_so_liberacoes_excepcionais(self):
        liberar_excepcionalmente(
            criar_aluna('Ana Lima', ativo=False), 'Vai pagar hoje', self.usuario,
        )
        registrar_entrada(criar_aluna('Bia Souza'))
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context['liberacoes']), 1)

    def test_total_por_atendente(self):
        outro = criar_usuario(Perfil.RECEPCAO)
        for nome in ('Ana Lima', 'Bia Souza'):
            liberar_excepcionalmente(
                criar_aluna(nome, ativo=False), 'Vai pagar hoje', self.usuario,
            )
        liberar_excepcionalmente(
            criar_aluna('Cris Dias', ativo=False), 'Vai pagar hoje', outro,
        )
        resposta = self.client.get(self.url)
        self.assertEqual(
            dict(resposta.context['por_atendente']),
            {str(self.usuario): 2, str(outro): 1},
        )

    def test_filtro_de_periodo(self):
        aluna = criar_aluna('Ana Lima', ativo=False)
        liberar_excepcionalmente(aluna, 'Vai pagar hoje', self.usuario)
        Frequencia.objects.update(data_hora=timezone.now() - timedelta(days=10))
        hoje = timezone.localdate()

        recente = self.client.get(self.url, {
            'inicio': (hoje - timedelta(days=1)).isoformat(), 'fim': hoje.isoformat(),
        })
        self.assertEqual(len(recente.context['liberacoes']), 0)

        ampla = self.client.get(self.url, {
            'inicio': (hoje - timedelta(days=11)).isoformat(), 'fim': hoje.isoformat(),
        })
        self.assertEqual(len(ampla.context['liberacoes']), 1)

    def test_data_invalida_nao_quebra_a_tela(self):
        resposta = self.client.get(self.url, {'inicio': 'abc', 'fim': 'xyz'})
        self.assertEqual(resposta.status_code, 200)

    def test_financeiro_nao_acessa_liberacoes_recepcao(self):
        self.client.force_login(criar_usuario(Perfil.FINANCEIRO))
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)

    def test_perfil_aluna_nao_acessa(self):
        self.client.force_login(criar_usuario(Perfil.ALUNO))
        self.assertEqual(self.client.get(self.url).status_code, 302)

class MatriculaVencidaTests(TestCase):
    """T18: vigência encerrada e não renovada bloqueia a entrada."""

    def aluna_com_inicio(self, meses_atras, automatica=False):
        from dateutil.relativedelta import relativedelta
        aluna = criar_aluna('Ana Vigencia', com_matricula=False)
        plano = Plano.objects.create(
            nome=f'Tri{next(_seq)}', periodicidade='trimestral', valor=Decimal('90.00'),
            taxa_adesao=Decimal('0.00'), dia_vencimento=10, renovacao_automatica=automatica,
        )
        inicio = timezone.localdate() - relativedelta(months=meses_atras)
        matricula = realizar_matricula(aluna, plano, inicio, 'pix')
        Cobranca.objects.filter(matricula=matricula).update(paga=True)
        return aluna, matricula

    def test_vigencia_encerrada_sem_renovar_bloqueia_mesmo_pago(self):
        aluna, _ = self.aluna_com_inicio(5)
        r = avaliar_acesso(aluna)
        self.assertFalse(r['sucesso'])
        self.assertEqual(r['status'], 'bloqueado')
        self.assertIn('vencida', r['mensagem'])

    def test_no_proprio_dia_do_fim_ja_esta_vencida(self):
        aluna, _ = self.aluna_com_inicio(3)
        self.assertEqual(avaliar_acesso(aluna)['status'], 'bloqueado')

    def test_um_dia_antes_do_fim_continua_liberada(self):
        from dateutil.relativedelta import relativedelta
        aluna, matricula = self.aluna_com_inicio(0)
        matricula.data_inicio = timezone.localdate() - relativedelta(months=3) + timedelta(days=1)
        matricula.save()
        self.assertEqual(avaliar_acesso(aluna)['status'], 'liberado')

    def test_entrada_vencida_nao_gera_frequencia(self):
        aluna, _ = self.aluna_com_inicio(5)
        r = registrar_entrada(aluna)
        self.assertFalse(r['registrada'])
        self.assertFalse(Frequencia.objects.filter(aluno=aluna).exists())

    def test_renovada_volta_a_ser_liberada(self):
        from financeiro.servicos import renovar_matricula
        aluna, matricula = self.aluna_com_inicio(3)
        self.assertEqual(avaliar_acesso(aluna)['status'], 'bloqueado')
        renovar_matricula(matricula, hoje=timezone.localdate())
        Cobranca.objects.filter(matricula=matricula).update(paga=True)
        self.assertEqual(avaliar_acesso(aluna)['status'], 'liberado')
