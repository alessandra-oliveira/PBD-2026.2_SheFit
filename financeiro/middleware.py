"""Renovação automática sem ninguém clicar e sem agendador externo (T18).

Na primeira requisição de cada dia, o sistema varre as matrículas de plano
automático e gera o ciclo seguinte das que chegaram ao fim da vigência.
É idempotente, o ciclo novo sempre começa no fim do anterior (não importa a hora
da varredura) e qualquer falha é registrada sem atrapalhar quem abriu a tela.
"""
import logging
import threading
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Em segundos: depois de uma falha, só tenta de novo depois deste intervalo.
ESPERA_APOS_FALHA = 300

_trava = threading.Lock()
_estado = {'dia': None, 'nao_antes_de': 0.0}


def reiniciar_estado():
    """Esquece o que já rodou (usado nos testes)."""
    _estado.update(dia=None, nao_antes_de=0.0)


def executar_renovacao_do_dia():
    """Roda a varredura se ainda não rodou hoje neste processo. Nunca levanta erro."""
    hoje = timezone.localdate()
    if _estado['dia'] == hoje or time.monotonic() < _estado['nao_antes_de']:
        return None
    # Outra requisição já está varrendo: não precisa esperar nem repetir.
    if not _trava.acquire(blocking=False):
        return None
    try:
        if _estado['dia'] == hoje:
            return None
        from .servicos import renovar_automaticas
        resumo = renovar_automaticas(hoje)
        for matricula_id, erro in resumo['erros']:
            logger.error("Renovação automática da matrícula #%s falhou: %s", matricula_id, erro)
        if resumo['ciclos']:
            logger.info(
                "Renovação automática: %s ciclo(s) em %s matrícula(s), %s cobrança(s).",
                resumo['ciclos'], resumo['matriculas'], resumo['cobrancas'],
            )
        _estado['dia'] = hoje
        return resumo
    except Exception:
        logger.exception("Renovação automática do dia falhou; tentará de novo em breve.")
        _estado['nao_antes_de'] = time.monotonic() + ESPERA_APOS_FALHA
        return None
    finally:
        _trava.release()


class RenovacaoAutomaticaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, 'RENOVACAO_AUTOMATICA_NA_REQUISICAO', True):
            executar_renovacao_do_dia()
        return self.get_response(request)