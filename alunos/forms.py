from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from .models import Aluno



class AlunoForm(forms.ModelForm):
    username = forms.CharField(label='Nome de usuário', max_length=150)
    password = forms.CharField(label='Senha', widget=forms.PasswordInput)

    class Meta:
        model = Aluno
        fields = [
            'nome', 'cpf', 'data_nascimento', 'endereco', 'telefone',
            'email', 'foto', 'contato_emergencia_nome', 'contato_emergencia_telefone',
        ]
        widgets = {
            'data_nascimento': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise ValidationError('Esse nome de usuário já está em uso.')
        return username

    def clean_cpf(self):
        cpf = self.cleaned_data['cpf']
        if Aluno.objects.filter(cpf=cpf).exists():
            raise ValidationError('Já existe um aluno cadastrado com esse CPF.')
        return cpf

    def clean_email(self):
        email = self.cleaned_data['email']
        if Aluno.objects.filter(email=email).exists():
            raise ValidationError('Já existe um aluno cadastrado com esse e-mail.')
        return email

    def clean_telefone(self):
        telefone = self.cleaned_data['telefone']
        if Aluno.objects.filter(telefone=telefone).exists():
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