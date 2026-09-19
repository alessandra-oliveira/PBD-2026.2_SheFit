from django import forms
from .models import Plano

class PlanoForm(forms.ModelForm):
    class Meta:
        model = Plano
        fields = [
            'nome',
            'descricao',
            'modalidades_incluidas',
            'periodicidade',
            'valor',
            'fidelidade_meses',
            'multa_cancelamento',
            'taxa_adesao',
            'dia_vencimento',
            'ativo'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Plano Gold SheFit'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descrição das regras ou público-alvo...'}),
            'modalidades_incluidas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Musculação livre, Aulas de Ritmos, Avaliação física...'}),
            'periodicidade': forms.Select(attrs={'class': 'form-control'}),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'fidelidade_meses': forms.NumberInput(attrs={'class': 'form-control'}),
            'multa_cancelamento': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'taxa_adesao': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dia_vencimento': forms.NumberInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }