from decimal import Decimal

from django import forms
from django.utils import timezone

from financeiro.models import Matricula


class PagamentoForm(forms.Form):
    valor = forms.DecimalField(
        label='Valor recebido',
        min_value=Decimal('0.01'),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0.01',
        }),
    )
    data_pagamento = forms.DateField(
        label='Data do pagamento',
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    forma_pagamento = forms.ChoiceField(
        label='Forma de pagamento',
        choices=Matricula.FORMA_PAGAMENTO_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    observacoes = forms.CharField(
        label='Observações',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def clean_data_pagamento(self):
        data_pagamento = self.cleaned_data['data_pagamento']
        if data_pagamento > timezone.localdate():
            raise forms.ValidationError('A data do pagamento não pode estar no futuro.')
        return data_pagamento


class EstornoForm(forms.Form):
    valor = forms.DecimalField(
        label='Valor do estorno',
        min_value=Decimal('0.01'),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0.01',
        }),
    )
    motivo = forms.CharField(
        label='Motivo',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

class CancelamentoForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo do cancelamento',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        error_messages={'required': 'Informe o motivo do cancelamento.'},
    )
    # O valor que a recepção mostrou à aluna. Volta junto com o POST para o
    # serviço conferir que o cancelamento não é confirmado por um valor e
    # cobrado por outro.
    multa_exibida = forms.DecimalField(
        max_digits=10, decimal_places=2, widget=forms.HiddenInput(),
    )

    def clean_motivo(self):
        motivo = self.cleaned_data['motivo'].strip()
        if not motivo:
            raise forms.ValidationError('Informe o motivo do cancelamento.')
        return motivo