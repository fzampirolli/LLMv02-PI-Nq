# Sistema de Correção Automática de Provas com IA — N Questões
 
Correção assíncrona de submissões do Moodle VPL usando LLMs (Groq, DeepSeek ou Gemini).
Para cada aluno, é gerado um arquivo `rubrica.txt` com a análise da IA por questão, além de uma comparação com a nota atribuída pelo Moodle.
 
As provas com mais de uma questão por atividade VPL devem ser criadas no MCTest ([https://mctest.ufabc.edu.br](https://mctest.ufabc.edu.br)), podendo ser com questões **paramétricas** e podem ser sorteadas para os alunos.
 
As soluções devem ser submetidas em uma única atividade VPL. O sistema suporta dois cenários:
 
- **Prova com múltiplas questões:** os arquivos devem seguir o padrão `Q1.*`, `Q2.*`, etc., onde `*` representa a extensão da linguagem escolhida pelo aluno (ex: `Q1.py`, `Q2.java`).
- **Prova com única questão:** o arquivo pode ter qualquer nome e extensão suportada (ex: `solucao.py`, `prova.c`).
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
│   ├── __init__.py          ← fábrica de clientes (Factory)
│   ├── base.py              ← lógica de retry e fallback entre modelos
│   ├── groq.py
│   ├── deepseek.py
│   └── gemini.py
├── core/                    ← lógica principal
│   ├── grader.py
│   └── utils.py
└── p3moodle/                ← pasta com submissões dos alunos
    ├── Nome Aluno - login/
    │   ├── 2026-03-04-10-14-39/       ← última submissão
    │   │   ├── Q1.py                  ← padrão para múltiplas questões
    │   │   ├── Q2.py
    │   │   └── rubrica.txt            ← gerado pela LLM (somente se avaliação válida)
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
  provider: "groq"   # opções: groq | deepseek | gemini

# --- Configuração da API do provedor escolhido ---
groq:
  api_url: "https://api.groq.com/openai/v1/chat/completions"
  api_key: "SUA_CHAVE_AQUI"
  temperature: 0.3
  models:
    - "llama-3.3-70b-versatile"   # tentados em ordem aleatória
    - "openai/gpt-oss-120b"       # para distribuir carga entre alunos
    - "llama-3.1-8b-instant"      # simultâneos e evitar rate limit
    - "openai/gpt-oss-20b"

# --- Configuração do Processamento de Provas ---
grading:
  prompt_file: "promptP3.txt"   # arquivo com rubricas
  weights:
    q1: 50
    q2: 50
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

O arquivo especificado em `grading.prompt_file` (ex: `promptP3.txt`) contém as rubricas de avaliação. Como as questões são **sorteadas e embaralhadas por aluno** no MCTest, a LLM recebe o prompt completo com todas as rubricas e:

1. Lê o código do aluno
2. Identifica o tipo da questão (ex: Tipo A ou Tipo B)
3. Aplica **apenas** a rubrica correspondente ao tipo identificado
4. Retorna a avaliação e a nota no formato: `NOTA FINAL: X/PESO`

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

[START_RUBRICA_B]
TIPO B — descrição
  ...
[END_RUBRICA_B]
```

> **Nota:** O prompt completo (com todos os tipos) é enviado em cada chamada, pois é necessário que a IA conheça todas as rubricas para identificar o tipo corretamente. Isso é intencional — não há como otimizar sem uma chamada prévia de identificação.

---

## 5. Comportamento do Sistema de Avaliação

### Identificação de arquivos por questão

| Cenário | Comportamento |
|---------|---------------|
| Prova com múltiplas questões | Busca `Q1.*`, `Q2.*` com extensão suportada |
| Prova com única questão | Aceita qualquer arquivo com extensão suportada |
| Aluno enviou só Q1 (prova de 2 questões) | Q1 avaliada, Q2 com nota 0 |
| Aluno enviou só Q2 (prova de 2 questões) | Q2 avaliada, Q1 com nota 0 |

### Geração do `rubrica.txt`

O arquivo **só é salvo** se a IA retornar ao menos uma avaliação válida para as questões que possuem código. Caso contrário, o arquivo não é criado, forçando uma nova consulta na próxima execução (sem cache inválido).

| Situação | Salva rubrica.txt? |
|----------|--------------------|
| Todas as questões com código avaliadas com sucesso | ✅ Sim |
| IA falhou em ao menos uma questão com código | ❌ Não — reprocessa tudo |
| Aluno sem nenhum arquivo de código | ❌ Não |
| Tipo identificado como DESCONHECIDO | ❌ Não |

### Fallback entre modelos (rate limit)

Quando há múltiplos modelos configurados, o sistema:

1. **Embaralha** a lista de modelos a cada chamada — alunos processados simultaneamente tendem a usar modelos diferentes, distribuindo o consumo de tokens por minuto (TPM)
2. **Respeita o tempo sugerido** pelo provedor no erro 429 (ex: `Please try again in 3.99s`), em vez de usar backoff fixo
3. **Tenta até 3 vezes** por modelo antes de passar ao próximo
4. **Interrompe imediatamente** em erros de autenticação (401) ou saldo insuficiente (402)

---

## 6. Baixar as Submissões do Moodle VPL

1. Acesse a atividade **VPL** no Moodle
2. Clique em **Lista de envios**
3. Clique na seta para baixo (⬇) no cabeçalho → **Baixar envios** ou 
**Baixar todos os envios**
4. Descompacte o `.zip` e mova para o projeto:

```bash
# macOS/Linux
mv ~/Downloads/p3moodle ./p3moodle

# Windows PowerShell
Move-Item "$env:USERPROFILE\Downloads\p3moodle" .\p3moodle
```

### ⚠️ Corrigir nomes das pastas

A versão atual do VPL baixa as pastas com `sobrenome nome - login`. É necessário corrigir isso executando:

```bash
bash renomear_pastas.sh p3moodle
```

---

## 7. Executar a Correção com IA

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
4. Para cada questão:
   - Localiza o arquivo de código (`Q1.*`, `Q2.*` ou qualquer arquivo para prova de 1 questão)
   - Seleciona um modelo aleatório da lista configurada em `config.yaml`
   - Envia o código + prompt à LLM
   - A LLM identifica o tipo e retorna a avaliação com a nota
5. Processa **todos os alunos em paralelo** (controle de concorrência)
6. Gera:
   - `rubrica.txt` dentro da pasta de cada aluno (somente se avaliação válida)
   - `{pasta}_ALL.txt` junta todos os arquivos `rubrica.txt` dos alunos
   - `{pasta}_relatorio.csv` com o resumo de todos os alunos

---

## 8. Estrutura do rubrica.txt

Cada aluno recebe um `rubrica.txt` com:

| Seção | Conteúdo |
|-------|----------|
| Resumo | Comparativo Moodle × IA com notas por questão |
| Por questão | Código do aluno + critérios aplicados + avaliação da IA |

---

## 9. Gerar Relatório CSV Consolidado
 
Após a execução, o sistema já gera automaticamente os arquivos, ex.:
 
```
p3moodle_ALL.csv
p3moodle_relatorio.csv
```
 
Se a opção `--log` foi utilizada (`bash run.sh config.yaml --log`), também gera:
 
```
log_correcao_20260418_1016.txt
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


---

## 10. Envio de Feedbacks por E-mail (Opcional)

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

## 11. Modelos LLM Disponíveis por Provedor

### Groq
| Modelo | Qualidade | Velocidade |
|--------|-----------|------------|
| `llama-3.3-70b-versatile` | Alta | Média |
| `openai/gpt-oss-120b` | Alta | Média |
| `llama-3.1-8b-instant` | Média | Rápida |
| `openai/gpt-oss-20b` | Média | Rápida |

> **Dica:** Configure múltiplos modelos no `config.yaml` para distribuir automaticamente a carga entre alunos processados em paralelo e evitar erros de rate limit (429).

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

## 12. Solução de Problemas

| Problema | Solução |
|----------|---------|
| `❌ Pasta de alunos não encontrada` | Verifique `paths.student_base_dir` no `config.yaml` |
| `python3: comando não encontrado` (Windows) | Use `python` em vez de `python3` |
| Nota IA = `?` | O prompt não retornou nota no formato esperado (`NOTA FINAL: X/PESO`) |
| Erro HTTP 429 (rate limit) | Configure múltiplos modelos — o sistema faz fallback automático |
| Tipo identificado como `DESCONHECIDO` | Revise as rubricas e características dos tipos no arquivo de prompt |
| Arquivo de código não encontrado | Verifique extensão em `supported_extensions`; para prova de 1 questão, certifique-se de que há exatamente 1 arquivo na pasta |
| `rubrica.txt` não gerado | A IA não retornou avaliação válida — verifique o log para detalhes |

---

## 13. Privacidade — O que é enviado à API

| Campo | Conteúdo | Dado pessoal? |
|-------|----------|----------------|
| `system` | Conteúdo do prompt (rubricas) | ❌ Não |
| `user` | Nome do arquivo + código-fonte | ❌ Não |

**Nunca são enviados:** nome do aluno, e-mail, login, RA ou CPF.

---

## 14. Segurança

O `config.yaml` contém suas chaves de API. Ele já está no `.gitignore`:

```
config.yaml
*.env
logs/
*_ALL.txt
*_relatorio.csv
```

**Nunca compartilhe nem publique o `config.yaml`.**
