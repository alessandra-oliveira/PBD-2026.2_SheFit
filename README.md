# SheFit

Sistema web Django para gestão de academias. O SheFit centraliza cadastro de
alunos, anamneses, matrículas, cobrança, acesso à recepção, turmas, treinos,
avaliações físicas e indicadores de retenção.

## Objetivos

- Centralizar a operação diária da academia.
- Controlar o ciclo financeiro da matrícula e seus pagamentos.
- Aplicar regras de acesso com base na situação da matrícula.
- Organizar turmas, vagas, lista de espera e frequência.
- Registrar a evolução de treinos e avaliações sem perder o histórico.
- Disponibilizar painéis diferentes para cada perfil de usuário.

## Funcionalidades implementadas

- Autenticação e painéis para administrador, recepção, professor, financeiro e aluno.
- Cadastro, edição, ativação e desativação de alunos.
- Anamnese com autorização para prática de atividade física.
- Cadastro de planos, modalidades, turmas e professores.
- Matrícula com geração de cobranças de adesão e mensalidades.
- Registro de pagamentos e estornos.
- Regras financeiras configuráveis para tolerância, juros, multa, bloqueio e trancamento.
- Cancelamento e renovação de matrícula, incluindo renovação automática quando configurada.
- Trancamento de matrícula, suspensão de cobranças, prorrogação da vigência e histórico.
- Validação de acesso na recepção e liberações excepcionais auditadas.
- Agendamento de turmas com controle de vagas e lista de espera.
- Fichas de treino, registro de execução, aderência e evolução de carga.
- Avaliações físicas imutáveis, correções encadeadas e comparação de evolução.
- Relatórios financeiros de inadimplência e receita, com exportação.
- Indicadores de frequência e retenção.

## Tecnologias

- Python 3.12, conforme o ambiente utilizado na validação local.
- Django 5.2.17.
- PostgreSQL.
- `django-cors-headers`.
- `python-decouple` para configurações por variáveis de ambiente.
- `psycopg2-binary` para conexão com PostgreSQL.
- Pillow para campos de imagem dos alunos.
- Templates Django, HTML, CSS e JavaScript.

As dependências diretas estão fixadas em `requirements.txt` para manter o
ambiente reproduzível.

## Arquitetura

O projeto usa a organização padrão de aplicações Django:

- `models.py`: entidades, relacionamentos, validações e restrições do banco.
- `forms.py`: formulários de entrada e validação das telas.
- `views.py`: controle das requisições, permissões e renderização.
- `servicos.py`: regras de negócio que não pertencem diretamente à camada HTTP.
- `urls.py`: rotas de cada aplicação.
- `templates/`: interfaces HTML por aplicação.
- `tests.py`: testes automatizados de modelos, serviços e views.
- `migrations/`: histórico do esquema do banco.

As views usam decorators de perfil para restringir telas. As regras financeiras,
de acesso, agendamento, trancamento, cancelamento e renovação são aplicadas nos
serviços e reutilizadas pelas views e pelos testes.

## Aplicações

| Aplicação | Responsabilidade |
| --- | --- |
| `accounts` | Usuários, perfis, login e painéis. |
| `alunos` | Cadastro, anamnese e situação financeira do aluno. |
| `financeiro` | Planos, matrículas, cobranças, pagamentos, regras e relatórios. |
| `recepcao` | Entrada, acesso excepcional, cancelamento, renovação e trancamento. |
| `turmas` | Modalidades, turmas, frequência e gestão por professores. |
| `agendamentos` | Reservas, lista de espera e cancelamentos de aulas. |
| `treinos` | Fichas, exercícios, execuções e evolução de carga. |
| `avaliacoes` | Avaliações físicas, correções e comparações. |
| `retencao` | Indicadores de frequência, aulas, avaliações e evolução. |

## Estrutura principal

```text
SheFit/
├── accounts/
├── agendamentos/
├── alunos/
├── avaliacoes/
├── financeiro/
├── recepcao/
├── retencao/
├── treinos/
├── turmas/
├── sheFit/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── static/
├── manage.py
├── requirements.txt
└── .env.example
```

## Pré-requisitos

- Python 3.12 ou compatível com Django 5.2.
- PostgreSQL em execução.
- Git.
- No Windows, PowerShell ou outro terminal capaz de executar o ambiente virtual.

## Configuração do ambiente

1. Clone o repositório e entre na pasta:

   ```powershell
   git clone https://github.com/alessandra-oliveira/PBD-2026.2_SheFit.git
   cd PBD-2026.2_SheFit
   ```

2. Crie e ative o ambiente virtual:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

   No Linux ou macOS:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```

4. Copie `.env.example` para `.env` e preencha os dados do PostgreSQL:

   ```powershell
   Copy-Item .env.example .env
   ```

   Nunca versione o arquivo `.env`.

5. Crie o banco configurado em `DB_NAME` no PostgreSQL e execute as migrações:

   ```bash
   python manage.py migrate
   ```

## Variáveis de ambiente

As configurações são carregadas por `python-decouple`:

| Variável | Finalidade |
| --- | --- |
| `DB_NAME` | Nome do banco PostgreSQL. |
| `DB_USER` | Usuário do banco. |
| `DB_PASSWORD` | Senha do banco. |
| `DB_HOST` | Host do banco. |
| `DB_PORT` | Porta do banco, normalmente `5432`. |
| `SECRET_KEY` | Chave secreta do Django. |
| `DEBUG` | Ativa ou desativa o modo de depuração. |
| `ALLOWED_HOSTS` | Hosts permitidos, separados por vírgula. |

Use valores locais ou fictícios no desenvolvimento e credenciais reais apenas
por mecanismos seguros de configuração.

## Execução

Inicie o servidor de desenvolvimento com:

```bash
python manage.py runserver
```

A aplicação fica disponível, por padrão, em
`http://127.0.0.1:8000/`.

Para criar um usuário administrador do Django:

```bash
python manage.py createsuperuser
```

## Rotas principais

O projeto usa páginas HTML renderizadas pelo Django; não há uma API REST
separada documentada no código atual. As principais rotas são:

| Prefixo | Uso |
| --- | --- |
| `/entrar/`, `/sair/` | Autenticação. |
| `/painel/` | Redirecionamento para o painel do perfil. |
| `/alunos/` | Cadastro, anamnese, matrícula e situação financeira. |
| `/financeiro/` | Planos, regras, dashboard e relatórios financeiros. |
| `/recepcao/` | Entrada, pagamentos, cancelamentos, renovações e trancamentos. |
| `/turmas/` | Turmas, modalidades e frequência. |
| `/agendamentos/` | Aulas agendadas e lista de espera. |
| `/treinos/` | Fichas, execuções e evolução. |
| `/avaliacoes/` | Avaliações físicas e comparações. |
| `/numeros/` | Indicadores de retenção. |
| `/admin/` | Administração nativa do Django. |

As permissões são aplicadas por perfil e não devem ser substituídas por acesso
direto às URLs.

## Banco de dados

O banco padrão é PostgreSQL. O esquema é versionado nas pastas `migrations/`
de cada aplicação. Para aplicar alterações:

```bash
python manage.py makemigrations
python manage.py migrate
```

Os principais relacionamentos conectam `Aluno` a `Perfil`, `Matricula` a
`Plano`, `Cobranca` e `Pagamento`, além de turmas, agendamentos, fichas,
execuções e avaliações. A situação da matrícula é calculada a partir dos
registros financeiros, cancelamentos e trancamentos; ela não é armazenada como
um campo editável.

## Testes

Execute toda a suíte com:

```bash
python manage.py test
```

Para validar uma aplicação específica:

```bash
python manage.py test financeiro
python manage.py test recepcao
python manage.py test avaliacoes
```

Antes de executar os testes, confirme que o PostgreSQL e as variáveis de
ambiente estão configurados. O projeto também desativa a renovação automática
durante `manage.py test` para permitir que os testes controlem esse fluxo.
