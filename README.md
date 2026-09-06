# SheFit

Sistema de gestão de academia com cobrança recorrente gerada pela matrícula, situação financeira calculada automaticamente, controle de acesso na entrada, turmas com vaga limitada, fichas de treino e evolução do aluno.

## Funcionalidades

- **Perfis e acesso**: painel de controle com permissões específicas para cada tipo de usuário (recepção, professor, financeiro).
- **Alunos e anamnese**: cadastro de alunos com ficha de saúde.
- **Modalidades e turmas**: cadastro de turmas com horário e capacidade de vagas.
- **Regras financeiras**: configuração de tolerância, juros, multa e bloqueio por inadimplência.
- **Matrícula e cobrança automática**: geração automática de cobranças a partir da matrícula do aluno.
- **Registro de pagamentos**: controle da situação de pagamento de cada aluno.

## Tecnologias

- Python
- Django

## Como rodar o projeto

1. Clone o repositório:
   ```bash
   git clone https://github.com/alessandra-oliveira/PBD-2026.2_SheFit.git
   cd PBD-2026.2_SheFit
   ```

2. Crie e ative o ambiente virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate      # Windows
   source venv/bin/activate   # Linux/Mac
   ```

3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

4. Rode as migrações:
   ```bash
   python manage.py migrate
   ```

5. Inicie o servidor:
   ```bash
   python manage.py runserver
   ```

6. Acesse em `http://127.0.0.1:8000/`

## Status do projeto

Em desenvolvimento...
