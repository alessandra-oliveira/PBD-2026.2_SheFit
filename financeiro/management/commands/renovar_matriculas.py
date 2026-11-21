from datetime import date

from django.core.management.base import BaseCommand

from financeiro.servicos import renovar_automaticas


class Command(BaseCommand):
    help = 'Renova as matrículas com renovação automática vencidas.'

    def add_arguments(self, parser):
        parser.add_argument('--data', help='Data de referência (AAAA-MM-DD). Padrão: hoje.')

    def handle(self, *args, **options):
        hoje = date.fromisoformat(options['data']) if options.get('data') else None
        resultado = renovar_automaticas(hoje=hoje)

        self.stdout.write(
            f"{resultado['ciclos']} ciclo(s) gerado(s) em "
            f"{resultado['matriculas']} matrícula(s), "
            f"{resultado['cobrancas']} cobrança(s) criada(s)."
        )
        for erro in resultado['erros']:
            self.stderr.write(f'Erro: {erro}')