from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .models import Perfil


PAPEIS_COLABORADORES = [
    (Perfil.Tipo.RECEPCAO, 'Recepção'),
    (Perfil.Tipo.PROFESSOR, 'Professor (Instrutor)'),
    (Perfil.Tipo.FINANCEIRO, 'Financeiro'),
    (Perfil.Tipo.ADMIN, 'Administrador'),
]


class CadastroColaboradorForm(forms.Form):
    """
    Formulário para o Administrador cadastrar novos colaboradores no sistema,
    definindo dados básicos (nome, usuário, e-mail, senha provisória e perfil).
    """
    nome = forms.CharField(
        label='Nome Completo',
        max_length=150,
        widget=forms.TextInput(attrs={
            'placeholder': 'Ex: Juliana Lima',
            'class': 'form-input',
            'required': True,
        })
    )

    username = forms.CharField(
        label='Nome de Usuário (Login)',
        max_length=150,
        widget=forms.TextInput(attrs={
            'placeholder': 'Ex: juliana.recepcao',
            'class': 'form-input',
            'required': True,
        })
    )

    email = forms.EmailField(
        label='E-mail',
        widget=forms.EmailInput(attrs={
            'placeholder': 'Ex: juliana@shefit.com.br',
            'class': 'form-input',
            'required': True,
        })
    )

    senha_provisoria = forms.CharField(
        label='Senha Provisória',
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Mínimo de 6 caracteres',
            'class': 'form-input',
            'required': True,
        })
    )

    tipo = forms.ChoiceField(
        choices=PAPEIS_COLABORADORES,
        label='Tipo de Perfil',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': True,
        })
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('Este nome de usuário já está em uso.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Este e-mail já está cadastrado no sistema.')
        return email

    def clean_senha_provisoria(self):
        senha = self.cleaned_data['senha_provisoria']
        if len(senha) < 6:
            raise ValidationError('A senha provisória deve conter no mínimo 6 caracteres.')
        return senha

    @transaction.atomic
    def save(self):
        nome_completo = self.cleaned_data['nome'].strip()
        partes_nome = nome_completo.split(' ', 1)
        first_name = partes_nome[0]
        last_name = partes_nome[1] if len(partes_nome) > 1 else ''

        username = self.cleaned_data['username']
        email = self.cleaned_data['email']
        senha = self.cleaned_data['senha_provisoria']
        tipo = self.cleaned_data['tipo']

        # Criação do usuário do Django
        usuario = User.objects.create_user(
            username=username,
            email=email,
            password=senha,
            first_name=first_name,
            last_name=last_name,
        )

        # Se for admin, concede acesso à interface administrativa do Django se aplicável
        if tipo == Perfil.Tipo.ADMIN:
            usuario.is_staff = True
            usuario.save(update_fields=['is_staff'])

        # Criação do perfil correspondente
        Perfil.objects.create(
            usuario=usuario,
            tipo=tipo
        )

        return usuario
