from django import forms
from .models import Plano
from decimal import Decimal
from django.db import transaction
from .models import Plano, RegraFinanceira, HistoricoRegraFinanceira

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

class RegraFinanceiraForm(forms.ModelForm):

    class Meta:
        model = RegraFinanceira
        fields = ['dias_tolerancia', 'juros_diario', 'multa_atraso', 'dias_bloqueio']
        widgets = {
            'dias_tolerancia': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
            'juros_diario': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.001'}),
            'multa_atraso': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'dias_bloqueio': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1'}),
        }

    def clean(self):
        dados = super().clean()
        tolerancia = dados.get('dias_tolerancia')
        bloqueio = dados.get('dias_bloqueio')
        if tolerancia is not None and bloqueio is not None and bloqueio < tolerancia:
            self.add_error(
                'dias_bloqueio',
                f'O bloqueio não pode acontecer antes do fim da tolerância ({tolerancia} dias).'
            )
        return dados

    def _formatar(self, campo, valor):
        """Deixa o valor no formato do banco (ex: 2.5 vira 2.50) pro histórico."""
        if isinstance(valor, Decimal):
            casas = self._meta.model._meta.get_field(campo).decimal_places
            return f"{valor:.{casas}f}"
        return str(valor)

    def salvar(self, usuario):
        alterados = list(self.changed_data)
        if not alterados:
            return []

        with transaction.atomic():
            regras = self.save(commit=False)
            regras.atualizado_por = usuario
            regras.save()
            HistoricoRegraFinanceira.objects.bulk_create([
                HistoricoRegraFinanceira(
                    campo=campo,
                    valor_anterior=self._formatar(campo, self.initial.get(campo)),
                    valor_novo=self._formatar(campo, self.cleaned_data[campo]),
                    alterado_por=usuario,
                    alterado_por_nome=usuario.get_username(),
                )
                for campo in alterados
            ])
        return alterados