from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import AvaliacaoFisica, TesteFisico

CAMPOS_AVALIACAO = [
    'data_avaliacao', 'peso_kg', 'altura_cm', 'percentual_gordura',
    'torax_cm', 'cintura_cm', 'quadril_cm', 'braco_cm', 'coxa_cm', 'panturrilha_cm',
    'observacoes',
]


class AvaliacaoFisicaForm(forms.ModelForm):
    """Formulário de uma nova avaliação.

    Não há campo de IMC (é calculado) nem de aluno/professor (vêm da URL e da
    sessão, para não poderem ser forjados pelo formulário).
    """

    class Meta:
        model = AvaliacaoFisica
        fields = CAMPOS_AVALIACAO
        widgets = {
            'data_avaliacao': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'},
                format='%Y-%m-%d',
            ),
            'observacoes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            if nome != 'data_avaliacao':
                campo.widget.attrs.setdefault('class', 'form-control')


class AvaliacaoCorrecaoForm(AvaliacaoFisicaForm):
    """Mesmo formulário, com o motivo da correção obrigatório."""

    class Meta(AvaliacaoFisicaForm.Meta):
        fields = CAMPOS_AVALIACAO + ['motivo_correcao']
        widgets = {
            **AvaliacaoFisicaForm.Meta.widgets,
            'motivo_correcao': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Ex.: peso digitado errado na balança de bioimpedância',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['motivo_correcao'].required = True


class BaseTesteFisicoFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        vistos = set()
        for form in self.forms:
            if not form.is_valid() or not form.cleaned_data:
                continue
            nome = form.cleaned_data.get('nome', '').strip().casefold()
            if not nome:
                continue
            if nome in vistos:
                raise forms.ValidationError(
                    'Há testes repetidos: cada teste só pode aparecer uma vez por avaliação.'
                )
            vistos.add(nome)


_WIDGETS_TESTE = {
    'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex.: Flexões em 1 min'}),
    'resultado': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
    'unidade': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex.: rep, s, m'}),
}


def testes_formset(extra=3):
    """Formset de testes com `extra` linhas em branco (ou pré-preenchidas)."""
    return inlineformset_factory(
        AvaliacaoFisica,
        TesteFisico,
        formset=BaseTesteFisicoFormSet,
        fields=['nome', 'resultado', 'unidade'],
        extra=extra,
        can_delete=False,
        widgets=_WIDGETS_TESTE,
    )