from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from alunos.models import Aluno
from .models import ExercicioTreino, FichaTreino, ExecucaoExercicio
from django.utils import timezone

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

    def clean_data_revisao(self):
        data = self.cleaned_data['data_revisao']
        if data < timezone.localdate():
            raise forms.ValidationError('A data de revisão não pode estar no passado.')
        return data

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

class ExecucaoExercicioForm(forms.ModelForm):
    class Meta:
        model = ExecucaoExercicio
        fields = ['data', 'carga_kg', 'series', 'repeticoes']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'carga_kg': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'series': forms.NumberInput(attrs={'min': '1'}),
            'repeticoes': forms.NumberInput(attrs={'min': '1'}),
        }

    def clean_data(self):
        data = self.cleaned_data['data']
        if data > timezone.localdate():
            raise forms.ValidationError('A data da execução não pode ser no futuro.')
        return data