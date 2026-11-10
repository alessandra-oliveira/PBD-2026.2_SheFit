"""Regras de negócio das avaliações físicas (sem HTTP, fáceis de testar)."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# (atributo, rótulo, unidade) — tudo que é comparável numa avaliação.
# `imc` é propriedade calculada; os demais são campos.
CAMPOS_COMPARAVEIS = [
    ('peso_kg', 'Peso', 'kg'),
    ('altura_cm', 'Altura', 'cm'),
    ('imc', 'IMC', ''),
    ('percentual_gordura', 'Percentual de gordura', '%'),
    ('torax_cm', 'Tórax', 'cm'),
    ('cintura_cm', 'Cintura', 'cm'),
    ('quadril_cm', 'Quadril', 'cm'),
    ('braco_cm', 'Braço', 'cm'),
    ('coxa_cm', 'Coxa', 'cm'),
    ('panturrilha_cm', 'Panturrilha', 'cm'),
]


@dataclass
class LinhaComparacao:
    rotulo: str
    unidade: str
    anterior: Optional[Decimal]
    posterior: Optional[Decimal]
    aviso: str = ''
    eh_teste: bool = False

    @property
    def diferenca(self):
        if self.aviso or self.anterior is None or self.posterior is None:
            return None
        return self.posterior - self.anterior

    @property
    def diferenca_texto(self):
        d = self.diferenca
        if d is None:
            return '—'
        return f'{d:+.2f}'.replace('.', ',')


def chave_cronologica(avaliacao):
    return (avaliacao.data_avaliacao, avaliacao.registrada_em, avaliacao.pk)


def ordenar_cronologicamente(a, b):
    """Devolve (anterior, posterior). A diferença é sempre posterior − anterior."""
    return tuple(sorted([a, b], key=chave_cronologica))


def comparar_avaliacoes(a, b):
    """Compara duas avaliações e devolve uma linha por medida.

    A ordem em que o usuário escolheu as avaliações não importa: o resultado
    é sempre "da mais antiga para a mais recente". Quando uma medida existe
    só numa das duas, ela aparece, mas sem diferença.
    """
    anterior, posterior = ordenar_cronologicamente(a, b)
    linhas = [
        LinhaComparacao(
            rotulo=rotulo,
            unidade=unidade,
            anterior=getattr(anterior, attr),
            posterior=getattr(posterior, attr),
        )
        for attr, rotulo, unidade in CAMPOS_COMPARAVEIS
    ]

    # Testes físicos: casados pelo nome (sem diferenciar maiúsculas/espaços).
    testes_ant = {t.nome.strip().casefold(): t for t in anterior.testes.all()}
    testes_pos = {t.nome.strip().casefold(): t for t in posterior.testes.all()}
    for chave in list(testes_ant) + [c for c in testes_pos if c not in testes_ant]:
        t_ant, t_pos = testes_ant.get(chave), testes_pos.get(chave)
        base = t_pos or t_ant
        aviso = ''
        if t_ant and t_pos and t_ant.unidade.strip().casefold() != t_pos.unidade.strip().casefold():
            aviso = 'Unidades diferentes entre as avaliações'
        linhas.append(LinhaComparacao(
            rotulo=base.nome,
            unidade=base.unidade,
            anterior=t_ant.resultado if t_ant else None,
            posterior=t_pos.resultado if t_pos else None,
            aviso=aviso,
            eh_teste=True,
        ))
    return anterior, posterior, linhas