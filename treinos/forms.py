from django import forms
from django.forms import inlineformset_factory

from alunos.models import Aluno
from .models import ExercicioTreino, FichaTreino


class FichaTreinoForm(forms.ModelForm):
    class Meta:
        model = FichaTreino
        fields = ['aluno', 'data_revisao']
        widgets = {
            'aluno': forms.HiddenInput(),
            'data_revisao': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'},
                format='%Y-%m-%d',
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aluno'].queryset = Aluno.objects.select_related('perfil').order_by('nome')
        self.fields['aluno'].label = 'Aluno'
        self.fields['aluno'].empty_label = 'Selecione um aluno'


ExercicioTreinoFormSet = inlineformset_factory(
    FichaTreino,
    ExercicioTreino,
    fields=['nome', 'series', 'repeticoes', 'carga_sugerida', 'observacoes'],
    extra=1,
    can_delete=False,
    widgets={
        'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do exercício'}),
        'series': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        'repeticoes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        'carga_sugerida': forms.NumberInput(
            attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}
        ),
        'observacoes': forms.Textarea(
            attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Observações (opcional)'}
        ),
    },
)
