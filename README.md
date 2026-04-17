# Sistema de Correção Automática de Provas com IA — N Questões

Correção assíncrona de submissões do Moodle VPL usando LLMs (Groq, DeepSeek ou Gemini).
Para cada aluno, é gerado um arquivo `rubrica.txt` com a análise da IA por questão, além de uma comparação com a nota atribuída pelo Moodle.

As provas são criadas no MCTest ([https://mctest.ufabc.edu.br](https://mctest.ufabc.edu.br)), com questões **paramétricas** e sorteadas para os alunos. As soluções devem ser submetidas em uma atividade VPL, contendo vários arquivos com nomes específicos: `Q1.*`, `Q2.*`, etc., onde `*` representa a **extensão da linguagem escolhida pelo aluno**.

> ⚠️ **A nota final é sempre atribuída pelo professor por meio de avaliação manual.**
> A correção da IA serve apenas como apoio ao processo de aprendizagem e pode conter imprecisões.

---

## Arquivos do Projeto

```
.
├── config.yaml              ← configuração (NUNCA versionar)
├── config.yaml.example      ← template de configuração
├── main.py                  ← script principal (async)
├── run.sh                   ← wrapper de execução
├── gerar_relatorio.py       ← converte ALL.txt em CSV
├── enviar_email.py          ← envia rubricas por e-mail
├── providers/               ← clientes das APIs
│   ├── __init__.py
│   ├── base.py
│   ├── groq.py
│   ├── deepseek.py
│   └── gemini.py
├── core/                    ← lógica principal
│   ├── grader.py
│   └── utils.py
└── p3moodle/                ← pasta com submissões dos alunos
    ├── Nome Aluno - login/
    │   ├── 2026-03-04-10-14-39/       ← última submissão
    │   │   ├── Q1.py
    │   │   ├── Q2.py
    │   │   └── rubrica.txt            ← gerado pela LLM
    │   └── 2026-03-04-10-14-39.ceg/
    │       └── execution.txt          ← correção do Moodle
    └── ...
```

---

## 1. Clonar o Projeto

```bash
git clone https://github.com/fzampirolli/LLMv02-PI-Nq.git
cd LLMv02-PI-Nq
```

---

## 2. Pré-requisitos

### Python 3.8+

```bash
# macOS/Linux
python3 --version

# Windows (PowerShell ou Git Bash)
python --version
```

### Instalar dependências

```bash
# macOS/Linux
pip3 install aiohttp pyyaml

# Windows
pip install aiohttp pyyaml
```

### Chave de API (escolha um provedor)

| Provedor | Obter chave | Plano gratuito |
|----------|-------------|----------------|
| **Groq** | [console.groq.com](https://console.groq.com) | 30 req/min |
| **DeepSeek** | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | Sim |
| **Gemini** | [aistudio.google.com](https://aistudio.google.com/app/apikey) | Sim |

---

## 3. Configuração Inicial

### Copiar o template

```bash
# macOS/Linux/Git Bash
cp config.yaml.example config.yaml

# Windows PowerShell
Copy-Item config.yaml.example config.yaml
```

### Editar o `config.yaml`

```yaml
# --- Provedor LLM ativo ---
llm:
  provider: "deepseek"   # opções: groq | deepseek | gemini

# --- Configuração da API do provedor escolhido ---
deepseek:
  api_url: "https://api.deepseek.com/v1/chat/completions"
  api_key: "SUA_CHAVE_AQUI"
  temperature: 0.3
  max_response_chars: 8000
  models:
    - "deepseek-chat"

# --- Configuração do Processamento de Provas ---
grading:
  prompt_file: "promptP3.txt"   # arquivo com rubricas
  weights:
    q1: 50
    q2: 50
  use_llm: true
  min_code_lines: 4
  supported_extensions:
    - py
    - java
    - c
    - cpp

# --- Configuração de Pastas ---
paths:
  student_base_dir: "p3moodle"   # ← NOME DA PASTA COM SUBMISSÕES
  output_rubric_filename: "rubrica.txt"
```

> ⚠️ **Nunca versione o `config.yaml`** — ele contém suas chaves de API.

---

## 4. O prompt.txt — Prompt Universal

### Estrutura do arquivo de prompt

O arquivo especificado em `grading.prompt_file` (ex: `promptP3.txt`) contém as rubricas de avaliação. A LLM:

1. Lê o código do aluno
2. Identifica o tipo da questão
3. Aplica a rubrica correspondente
4. Retorna a nota no formato: `Nota: X + Y + Z = TOTAL/PESO`

### Exemplo de rubrica no prompt

Ver arquivo `promptP3.txt` como exemplo.

```
[START_RUBRICA_A]
TIPO A — descrição
  Critério 1 — Entrada de dados        (5 pts)
  Critério 2 — Lógica das condicionais (30 pts)
  Critério 3 — Saída                  (15 pts)
  Total: 50 pts
[END_RUBRICA_A]
```

---

## 5. Baixar as Submissões do Moodle VPL

1. Acesse a atividade **VPL** no Moodle
2. Clique em **Lista de envios**
3. Clique na seta para baixo (⬇) no cabeçalho → **Baixar todos os envios**
4. Descompacte o `.zip` e mova para o projeto:

```bash
# macOS/Linux
mv ~/Downloads/p3moodle ./p3moodle

# Windows PowerShell
Move-Item "$env:USERPROFILE\Downloads\p3moodle" .\p3moodle
```

### ⚠️ Corrigir nomes das pastas (se necessário)

Se os nomes das pastas vierem com acentos ou espaços problemáticos:

```bash
bash renomear_pastas.sh p3moodle
```

---

## 6. Executar a Correção com IA

### Usando o script wrapper (recomendado)

```bash
# macOS/Linux
chmod +x run.sh
bash run.sh config.yaml

# Windows Git Bash
bash run.sh config.yaml

# Com log ativado
bash run.sh config.yaml --log
```


### O que acontece durante a execução

1. O sistema carrega o `config.yaml`
2. Para cada aluno, localiza a **última submissão** (pasta com timestamp)
3. Extrai a nota do Moodle do arquivo `.ceg/execution.txt`
4. Para cada questão (`Q1.*`, `Q2.*`):
   - Envia o código + prompt à LLM
   - A LLM retorna a avaliação e a nota
5. Processa **todos os alunos em paralelo** (controle de concorrência)
6. Gera:
   - `rubrica.txt` dentro da pasta de cada aluno
   - `{pasta}_relatorio.csv` com o resumo de todos os alunos

---

## 7. Estrutura do rubrica.txt

Cada aluno recebe um `rubrica.txt` com:

| Seção | Conteúdo |
|---|---|
| Cabeçalho | Nome do aluno, data, questões e pesos |
| Correção Moodle | Nota extraída do `execution.txt` |
| Por questão | Código + avaliação da IA por critério |
| Resumo | Comparativo Moodle × IA |

---

## 8. Gerar Relatório CSV Consolidado

Após a execução, o sistema já gera automaticamente o arquivo:

```
p3moodle_relatorio.csv
```

### Estrutura do CSV

| Coluna | Descrição |
|--------|-----------|
| Nome | Nome completo do aluno |
| Login | Login Moodle |
| Q1_Moodle | Nota questão 1 (Moodle) |
| Q2_Moodle | Nota questão 2 (Moodle) |
| Q1_IA | Nota questão 1 (IA) |
| Q2_IA | Nota questão 2 (IA) |
| Total_Moodle | Soma das notas Moodle |
| Total_IA | Soma das notas IA |
| Diferenca | `Total_IA - Total_Moodle` |

### Converter ALL.txt para CSV (alternativa manual)

Se precisar converter um arquivo `_ALL.txt` existente:

```bash
python3 gerar_relatorio.py p3moodle_ALL.txt
```

---

## 9. Envio de Feedbacks por E-mail (Opcional)

```bash
# macOS/Linux
python3 enviar_email.py

# Windows
python enviar_email.py
```

### Configuração de e-mail no `config.yaml`

```yaml
email:
  smtp_server: smtp.ufabc.edu.br
  smtp_port: 587
  from_address: professor@ufabc.edu.br
  password: "SUA_SENHA"
  use_tls: true

templates:
  assunto: "Rubricas geradas por IA - Prova - {login}@aluno.ufabc.edu.br"
  corpo: |
    Prezado(a) {nome_pasta},
    
    Segue em anexo a rubrica de correção gerada por IA.
    
    Atenciosamente,
    Prof.
```

> ⚠️ Teste com seu próprio e-mail antes de enviar para os alunos.

---

## 10. Modelos LLM Disponíveis por Provedor

### Groq
| Modelo | Qualidade | Velocidade |
|--------|-----------|------------|
| `llama-3.3-70b-versatile` | Alta | Média |
| `openai/gpt-oss-120b` | Alta | Média |
| `llama-3.1-8b-instant` | Média | Rápida |

### DeepSeek
| Modelo | Descrição |
|--------|-----------|
| `deepseek-chat` | Modelo conversacional padrão |
| `deepseek-coder` | Especializado em código |
| `deepseek-reasoner` | Raciocínio profundo |

### Gemini
| Modelo | Descrição |
|--------|-----------|
| `gemini-2.0-flash` | Rápido, boa qualidade |
| `gemini-2.5-flash` | Mais recente |
| `gemini-2.5-pro` | Melhor qualidade |

---

## 11. Solução de Problemas

| Problema | Solução |
|----------|---------|
| `❌ Pasta de alunos não encontrada` | Verifique `paths.student_base_dir` no `config.yaml` |
| `python3: comando não encontrado` (Windows) | Use `python` em vez de `python3` |
| Nota IA = `?` | O prompt não tem a linha `Nota: X + Y + Z = TOTAL` |
| Erro HTTP 429 (muitas requisições) | Reduza `--concurrent` ou aumente intervalo |
| Tipo identificado como `DESCONHECIDO` | Revise as rubricas no arquivo de prompt |
| Arquivo de código não encontrado | Verifique extensão em `supported_extensions` |

---

## 12. Privacidade — O que é enviado à API

| Campo | Conteúdo | Dado pessoal? |
|-------|----------|----------------|
| `system` | Conteúdo do prompt (rubricas) | ❌ Não |
| `user` | Nome do arquivo + código-fonte | ❌ Não |

**Nunca são enviados:** nome do aluno, e-mail, login, RA ou CPF.

---

## 13. Segurança

O `config.yaml` contém suas chaves de API. Ele já está no `.gitignore`:

```
config.yaml
*.env
logs/
*_ALL.txt
*_relatorio.csv
```

**Nunca compartilhe nem publique o `config.yaml`.**
