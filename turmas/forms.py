from django import forms
from .models import Modalidade, Turma


class ModalidadeForm(forms.ModelForm):
    class Meta:
        model = Modalidade
        fields = ['nome', 'descricao']


class TurmaForm(forms.ModelForm):
    class Meta:
        model = Turma
        fields = ['modalidade', 'dia_semana', 'horario', 'professor', 'sala', 'capacidade_maxima']
        widgets = {
            'horario': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean_capacidade_maxima(self):
        capacidade = self.cleaned_data.get('capacidade_maxima')
        if capacidade is not None and capacidade <= 0:
            raise forms.ValidationError('A capacidade deve ser maior que zero.')
        return capacidade