from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from .models import Aluno, Anamnese
from financeiro.models import Matricula
from django.contrib.auth.models import User
from django.db import transaction   
from accounts.models import Perfil    

class AlunoForm(forms.ModelForm):
    """Cadastro e edição de aluno.

    No CADASTRO pede usuário e senha e, ao salvar, cria User + Perfil(aluno) +
    Aluno juntos (tudo ou nada). Na EDIÇÃO esses dois campos não existem e a
    checagem de duplicidade ignora o próprio registro.
    """
    username = forms.CharField(label='Nome de usuário', max_length=150)
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)

    class Meta:
        model = Aluno
        fields = [
            'nome', 'cpf', 'data_nascimento', 'endereco', 'telefone',
            'email', 'foto', 'contato_emergencia_nome', 'contato_emergencia_telefone',
        ]
        widgets = {
            'data_nascimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.editando = bool(self.instance and self.instance.pk)
        if self.editando:
            del self.fields['username']
            del self.fields['password']

    def _duplicado(self, campo, valor):
        outros = Aluno.objects.filter(**{campo: valor})
        if self.editando:
            outros = outros.exclude(pk=self.instance.pk)
        return outros.exists()

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise ValidationError('Esse nome de usuário já está em uso.')
        return username

    def clean_cpf(self):
        cpf = self.cleaned_data['cpf']
        if self._duplicado('cpf', cpf):
            raise ValidationError('Já existe um aluno cadastrado com esse CPF.')
        return cpf

    def clean_email(self):
        email = self.cleaned_data['email']
        if self._duplicado('email', email):
            raise ValidationError('Já existe um aluno cadastrado com esse e-mail.')
        return email

    def clean_telefone(self):
        telefone = self.cleaned_data['telefone']
        if self._duplicado('telefone', telefone):
            raise ValidationError('Já existe um aluno cadastrado com esse telefone.')
        return telefone

    def clean_password(self):
        password = self.cleaned_data.get('password')
        username = self.cleaned_data.get('username', '')
        try:
            validate_password(password, user=User(username=username))
        except ValidationError as erros:
            raise ValidationError(erros.messages)
        return password

    @transaction.atomic
    def save(self, commit=True):
        if self.editando:
            return super().save(commit=commit)

        # Cadastro novo: o aluno nasce inativo até a anamnese ser autorizada.
        usuario = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password'],
            email=self.cleaned_data['email'],
            first_name=self.cleaned_data['nome'].split(' ')[0][:150],
        )
        perfil = Perfil.objects.create(usuario=usuario, tipo=Perfil.ALUNO)
        aluno = super().save(commit=False)
        aluno.perfil = perfil
        aluno.ativo = False
        if commit:
            aluno.save()
        return aluno
    


class AnamneseForm(forms.ModelForm):
    class Meta:
        model = Anamnese
        fields = [
            'restricoes_medicas',
            'historico_lesoes',
            'condicoes_cronicas',
            'autorizacao_atividade_fisica',
        ]
        widgets = {
            'restricoes_medicas': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control',
                'placeholder': 'Ex: Problemas cardíacos, dores na coluna, restrições articulares...'
            }),
            'historico_lesoes': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control',
                'placeholder': 'Ex: Rompimento de ligamento, cirurgias prévias...'
            }),
            'condicoes_cronicas': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control',
                'placeholder': 'Ex: Hipertensão, asma, diabetes...'
            }),
            'autorizacao_atividade_fisica': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'restricoes_medicas': 'Restrições Médicas',
            'historico_lesoes': 'Histórico de Lesões',
            'condicoes_cronicas': 'Condições Crônicas',
            'autorizacao_atividade_fisica': 'Declaro autorização para a prática de atividades físicas',
        }

    def clean_autorizacao_atividade_fisica(self):
        autorizado = self.cleaned_data.get('autorizacao_atividade_fisica')
        if not autorizado:
            raise ValidationError(
                'A autorização para a prática de atividade física é obrigatória para liberar o aluno.'
            )
        return autorizado


class MatriculaForm(forms.ModelForm):
    """Só lista alunos que PODEM ser matriculados (ativos, com anamnese e
    autorização). A regra dura continua no serviço (realizar_matricula); este
    filtro só evita que a recepção escolha alguém que seria barrado."""

    class Meta:
        model = Matricula
        fields = ['aluno', 'plano', 'data_inicio', 'forma_pagamento']
        widgets = {
            'aluno': forms.Select(attrs={'class': 'form-control'}),
            'plano': forms.Select(attrs={'class': 'form-control'}),
            'data_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
            'forma_pagamento': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aluno'].queryset = Aluno.objects.filter(
            ativo=True, anamnese__autorizacao_atividade_fisica=True,
        )