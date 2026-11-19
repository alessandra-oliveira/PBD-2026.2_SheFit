from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Execucao, ExecucaoExercicio, FichaTreino, ItemExecucao


def ficha_ativa(aluno):
    return FichaTreino.objects.filter(aluno=aluno, ativa=True).first()


def registrar_execucao(aluno, itens, observacoes='', data=None):
    """Registra um treino feito na ficha ATIVA da aluna (T14).

    itens: lista de {'exercicio_id': int, 'carga_efetiva': Decimal | None}.
    Cria o registro com cópia dos dados da ficha; depois de criado, não muda mais.
    As cargas informadas também alimentam a evolução da T21 (ExecucaoExercicio).
    """
    ficha = ficha_ativa(aluno)
    if ficha is None:
        raise ValidationError('Você não tem ficha de treino ativa.')

    hoje = timezone.localdate()
    data = data or hoje
    if data > hoje:
        raise ValidationError('A data do treino não pode estar no futuro.')
    if data < timezone.localtime(ficha.criada_em).date():
        raise ValidationError('A data do treino não pode ser anterior à criação da ficha.')
    if not itens:
        raise ValidationError('Marque pelo menos um exercício feito.')

    exercicios = {e.pk: e for e in ficha.exercicios.all()}
    vistos = set()
    for item in itens:
        pk = item.get('exercicio_id')
        if pk not in exercicios:
            raise ValidationError('Exercício não pertence à ficha ativa.')
        if pk in vistos:
            raise ValidationError('Exercício marcado mais de uma vez.')
        vistos.add(pk)
        carga = item.get('carga_efetiva')
        if carga is not None and carga < 0:
            raise ValidationError('A carga não pode ser negativa.')

    with transaction.atomic():
        execucao = Execucao.objects.create(
            aluno=aluno,
            ficha=ficha,
            data=data,
            observacoes=(observacoes or '').strip(),
            total_prescritos=len(exercicios),
        )
        ItemExecucao.objects.bulk_create([
            ItemExecucao(
                execucao=execucao,
                exercicio=exercicios[item['exercicio_id']],
                nome=exercicios[item['exercicio_id']].nome,
                carga_prescrita=exercicios[item['exercicio_id']].carga_sugerida,
                carga_efetiva=item.get('carga_efetiva'),
            )
            for item in itens
        ])
        ExecucaoExercicio.objects.bulk_create([
            ExecucaoExercicio(
                aluno=aluno,
                exercicio=exercicios[item['exercicio_id']],
                data=data,
                carga_kg=item['carga_efetiva'],
            )
            for item in itens
            if item.get('carga_efetiva') is not None
        ])
    return execucao


def aderencia(aluno, inicio, fim):
    """Exercícios feitos sobre os prescritos, nos treinos registrados no período."""
    execucoes = Execucao.objects.filter(aluno=aluno, data__gte=inicio, data__lte=fim)
    prescritos = execucoes.aggregate(total=Sum('total_prescritos'))['total'] or 0
    feitos = ItemExecucao.objects.filter(execucao__in=execucoes).count()
    return {
        'treinos': execucoes.count(),
        'feitos': feitos,
        'prescritos': prescritos,
        'percentual': round(feitos * 100 / prescritos) if prescritos else 0,
    }


def evolucao_carga(aluno):
    """Cargas efetivas por exercício, da mais antiga para a mais recente."""
    itens = (
        ItemExecucao.objects
        .filter(execucao__aluno=aluno, carga_efetiva__isnull=False)
        .select_related('execucao')
        .order_by('execucao__data', 'execucao_id')
    )
    evolucao = {}
    for item in itens:
        evolucao.setdefault(item.nome, []).append((item.execucao.data, item.carga_efetiva))
    return evolucao