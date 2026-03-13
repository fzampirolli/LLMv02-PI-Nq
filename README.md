# Sistema de Correção Automática de Provas com IA — N Questões

Correção assíncrona de submissões do Moodle VPL usando a API Groq (LLMs).
Para cada aluno, é gerado um arquivo `rubrica.txt` com a análise da IA por questão, além de uma comparação com a nota atribuída pelo Moodle.

As provas são criadas no MCTest ([https://mctest.ufabc.edu.br](https://mctest.ufabc.edu.br)), com questões **paramétricas** e sorteadas para os alunos. As soluções devem ser submetidas em uma atividade VPL, contendo vários arquivos com nomes específicos: `Q1.*`, `Q2.*`, etc., onde `*` representa a **extensão da linguagem escolhida pelo aluno**.

> ⚠️ **A nota final é sempre atribuída pelo professor por meio de avaliação manual.**
> A correção da IA serve apenas como apoio ao processo de aprendizagem e pode conter imprecisões.

---

## Arquivos do Projeto

```
.
├── runProvaNq.sh           ← script principal (entrypoint)
├── graderNq.py             ← orquestrador assíncrono
├── llm_interface_prova.py  ← cliente LLM (aiohttp + retry)
├── enviar_email.py         ← envio de feedbacks por e-mail (opcional)
├── config.yaml             ← suas credenciais e configurações (NÃO versionar)
├── config.yaml.example     ← template de configuração
├── prompt.txt              ← prompt universal: a LLM identifica o tipo e avalia
├── gerar_relatorio.py      ← gera CSV a partir do relatório consolidade TXT
└── p1moodle0/              ← pasta com submissões dos alunos (gerada pelo Moodle)
    ├── Nome Aluno - login/
    │   ├── 2026-03-04-10-14-39/       ← última submissão (pasta timestamp)
    │   │   ├── Q1.py                  ← código questão 1
    │   │   └── Q2.py                  ← código questão 2
    │   └── 2026-03-04-10-14-39.ceg/
    │       └── execution.txt          ← correção automática do Moodle
    └── ...
```

---

## 1. Clonar o Projeto

### macOS e Linux

```bash
git clone https://github.com/fzampirolli/LLMv02-PI-Nq.git
cd LLMv02-PI-Nq
```

### Windows

Instale o [Git para Windows](https://git-scm.com/download/win) se ainda não tiver.  
Abra o **Git Bash** (recomendado) ou o PowerShell e execute:

```bash
git clone https://github.com/fzampirolli/LLMv02-PI-Nq.git
cd LLMv02-PI-Nq
```

> **Recomendação para Windows:** use o **Git Bash** para todos os comandos deste guia.  
> O `runProvaNq.sh` requer bash — no PowerShell use o caminho alternativo indicado na seção de execução.

---

## 2. Pré-requisitos

### Python 3.8+

| Sistema | Verificar versão | Instalar |
|---|---|---|
| macOS | `python3 --version` | [python.org](https://www.python.org/downloads/) ou `brew install python` |
| Linux | `python3 --version` | `sudo apt install python3` (Debian/Ubuntu) |
| Windows | `python --version` | [python.org](https://www.python.org/downloads/) — marque **"Add to PATH"** na instalação |

### Instalar dependências Python

**macOS / Linux:**
```bash
pip3 install aiohttp pyyaml
```

**Windows (PowerShell ou Git Bash):**
```bash
pip install aiohttp pyyaml
```

Se houver erro de permissão no Linux/macOS:
```bash
pip3 install aiohttp pyyaml --break-system-packages
```

### Chave de API Groq (gratuita)

1. Acesse [console.groq.com](https://console.groq.com) e crie uma conta
2. Vá em **API Keys** → **Create API Key**
3. Copie a chave (começa com `gsk_...`) — você usará no `config.yaml`

---

## 3. Configuração Inicial

### Copiar o template de configuração

**macOS / Linux / Git Bash:**
```bash
cp config.yaml.example config.yaml
```

**Windows (PowerShell):**
```powershell
Copy-Item config.yaml.example config.yaml
```

### Editar o config.yaml

```yaml
# Chave da API Groq (obrigatório)
groq:
  api_url: "https://api.groq.com/openai/v1/chat/completions"
  api_key: "gsk_..."          # cole sua chave aqui
  temperature: 0.7
  max_response_chars: 100000
  min_response_chars: 5
  models:
    - "llama-3.3-70b-versatile"
    - "openai/gpt-oss-120b"
    - "llama-3.1-8b-instant"
    - "openai/gpt-oss-20b"

# Credenciais de e-mail SMTP (só necessário para enviar feedbacks)
email:
  smtp_server: smtp.ufabc.edu.br
  smtp_port: 587
  from_address: seu_email@ufabc.edu.br
  password: "sua_senha"

templates:
  assunto: "Rubricas e Correções geradas por LLM - Prova1 - {login}@aluno.ufabc.edu.br"
  corpo: |
    Prezado(a) {nome_pasta},

    A sua nota da prova já está disponível no Moodle.

    Em anexo, envio também as competências avaliadas e uma correção detalhada gerada automaticamente por Inteligência Artificial.

    Ressalto que essa correção gerada por IA PODE conter imprecisões ou erros, mas pode ser útil como apoio ao seu processo de aprendizagem na disciplina.

    Uma sugestão é submeter os seus códigos contidos neste arquivo, juntamente com as RUBRICAS abaixo, a outros modelos de LLM para comparação. Isso pode ajudar a identificar possíveis erros, além de oferecer diferentes perspectivas sobre o código e sobre os critérios de avaliação.

    Caso tenha dúvidas sobre a correção apresentada no Moodle, estou à disposição para esclarecimentos.

    Atenciosamente,  
    Prof. Francisco Zampirolli  

    PS.: Explicando o processo: a última versão salva no Moodle foi anexada ao *prompt* e enviadas para um dos LLMs escolhidos aleatoriamente entre os modelos abaixo:

    modelos = (
        "llama-3.3-70b-versatile"
        "openai/gpt-oss-120b"
        "llama-3.1-8b-instant"
        "openai/gpt-oss-20b"
    )

    O processo é repetido até que seja obtida uma resposta com conteúdo.  
    Alguns desses modelos apresentam respostas melhores, mas, devido à limitação de 30 requisições por minuto na versão gratuita do Groq (https://console.groq.com/settings/limits), foi necessário realizar um sorteio aleatório entre eles.

    """
    RUBRICA de Correção Automática - TIPO A
    Desenvolveu corretamente **condicionais**:

    1) Entrada de dados: X (max: 5) 
      Leitura correta dos valores de entrada com input() e
      conversão adequada para inteiro ou float.

    2) Lógica das Condicionais: Y (max: 30) 
      Implementação correta das faixas de cada nutriente, sem sobreposições. 
      Lógica para a Avaliação Final: uso de if/else para definir "Equilibrada" ou "Desequilibrada".

    3) Saída: Z (max: 15) 
      Exibição do status individual de cada nutriente seguindo o modelo. 
      Exibição da linha final "Avaliacao".

    Nota: X + Y + Z  (max: 50)
    """

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    """
    RUBRICA de Correção Automática - TIPO B
    Desenvolveu corretamente **laços** de repetição:

    1) Entrada e Organização: X (max: 5) 
      Leitura e conversão dos dois números inteiros a e b.

    2) Estrutura de Repetição: Y (max: 35) 
      Inicialização correta da variável acumuladora (soma = 0 ou produto = 1). 
      Implementação correta do laço e dos filtros (paridade ou potência). 
      Inclusividade: garantir que o limite b seja incluído (ex.: range(a, b + 1)).

    3) Saída: Z (max: 10) 
      Impressão do valor final da acumulação, sem caracteres extras.

    Nota: X + Y + Z  (max: 50)
    """

# --- Configuração do Processamento de Provas ---
grading:
  # ── Prompt universal ────────────────────────────────────────────────────
  # A LLM lê o código do aluno, identifica o tipo da questão sozinha
  # e aplica a rubrica correspondente — tudo em uma única chamada.
  #
  # Para adicionar novos tipos (vetor, matriz, recursão...):
  # basta acrescentar a rubrica do novo tipo dentro do prompt.txt.
  prompt_file: "prompt.txt"

  weights:
    q1: 50
    q2: 50
  use_llm: true                  # true = ativa análise da IA; false = apenas notas do Moodle
  min_code_lines: 4              # mínimo de linhas para enviar à IA
  supported_extensions:          # ordem de prioridade
    - py
    - java
    - c     
    - cpp    

# --- Configuração de Pastas ---
paths:
  student_base_dir: "p1moodle0"   # pasta raiz com as submissões
  output_rubric_filename: "rubrica.txt"
```

> ⚠️ **Nunca versione o `config.yaml`** — ele contém sua API key e senha de e-mail.  
> Ele já está listado no `.gitignore` do projeto.

---

### Usar Gmail como remetente (opcional)

Para enviar pelo Gmail, gere uma **Senha de App** (sua senha normal não funciona):

1. Acesse **https://myaccount.google.com/apppasswords** (requer login)
2. Em "Nome do app", coloque qualquer nome, ex: `MCTest`
3. Clique em **Criar** → será gerada uma senha de 16 caracteres
4. Copie e cole no `config.yaml`:

```yaml
email:
  smtp_server: smtp.gmail.com
  smtp_port: 587
  from_address: seu_email@gmail.com
  password: "abcdefghijklmnop"   # 16 caracteres gerados pelo Google
  use_tls: true
```

> ℹ️ Se a opção "Senhas de app" não aparecer, ative primeiro a **verificação em duas etapas** em https://myaccount.google.com/security


---

## 4. O prompt.txt — Prompt Universal

### Por que um prompt universal?

Em provas com questões sorteadas, **o professor não sabe antecipadamente qual tipo de questão cada aluno recebeu**. A abordagem tradicional de usar um prompt por tipo (ex: `promptA.txt`, `promptB.txt`) exigiria detectar o tipo pelo código do aluno — o que é frágil para questões com vetores, matrizes, recursão, etc.

A solução adotada é um **prompt universal**: a própria LLM lê o código do aluno, identifica o tipo da questão e aplica a rubrica correspondente — tudo em **uma única chamada à API**.

### Estrutura do prompt.txt

O arquivo tem duas etapas que a LLM executa em sequência:

**ETAPA 1 — Identificação do tipo**

A LLM analisa os padrões do código (estruturas usadas, nomes de variáveis, lógica geral) e declara na **primeira linha** da resposta:

```
Tipo identificado: A
```

Cada tipo é descrito no prompt com suas características e indícios típicos no código:

```
TIPO A — Classificação com if/elif/else
  Características: lê N valores numéricos, classifica cada um em categorias
  usando estruturas condicionais, determina se o conjunto é "Equilibrado"
  ou "Desequilibrado".
  Indícios: múltiplos if/elif, comparações com < > <= >=,
  strings como "Abaixo", "Adequado", "Acima".

TIPO B — Acumulação com laço (somatório ou produtório)
  Características: lê dois inteiros a e b, itera sobre o intervalo
  filtrando pares ou ímpares, acumula soma ou produto dos quadrados.
  Indícios: for/while com range, filtro i%2, acumulador += ou *=.
```

**ETAPA 2 — Avaliação pela rubrica do tipo identificado**

A LLM aplica apenas a rubrica do tipo que ela mesma identificou. Cada tipo tem sua rubrica completa dentro do mesmo arquivo:

```
══ RUBRICA DO TIPO A — Classificação com if/elif/else ══
  Critério 1 — Leitura e tipagem        (5 pts)
  Critério 2 — Estrutura if/elif/else  (30 pts)
  Critério 3 — Classificação e saída   (15 pts)
  Total: 50 pts

══ RUBRICA DO TIPO B — Acumulação com laço ══
  Critério 1 — Leitura e tipagem        (5 pts)
  Critério 2 — Laço com filtro          (35 pts)
  Critério 3 — Saída                   (10 pts)
  Total: 50 pts
```

Cada rubrica também lista os **erros comuns** do tipo para que a LLM os verifique explicitamente (ex: `range(a,b)` sem `+1`, inicializar produto com `0`, comparar tupla com inteiro).

### Formato obrigatório da resposta

O `prompt.txt` instrui a LLM a terminar sempre com:

```
Nota: X + Y + Z = TOTAL/PESO
```

Onde `X`, `Y`, `Z` são as notas de cada critério e `PESO` é o peso máximo da questão (injetado automaticamente pelo `graderNq.py` com base no `config.yaml`). Essa linha é usada pelo sistema para extrair a nota e exibi-la no resumo comparativo.

### Como adaptar para outra prova

Para uma nova prova com tipos diferentes, edite apenas o `prompt.txt`:

1. **Atualize a ETAPA 1** com as características e indícios dos novos tipos
2. **Substitua as rubricas** pelos critérios e pesos da nova prova
3. **Para adicionar um novo tipo** (ex: vetor, matriz, recursão), acrescente uma nova seção `══ RUBRICA DO TIPO C ══` com seus critérios

Nenhum arquivo Python precisa ser alterado.

### Vantagens em relação a outras abordagens

| Abordagem | Robustez | Flexibilidade | Chamadas API |
|---|---|---|---|
| Regex no código | ❌ Falha com vetores, recursão | ❌ Requer manutenção | 1 |
| Mapeamento explícito (`q1: promptB.txt`) | ✅ Confiável | ⚠️ Professor precisa saber o tipo de cada aluno | 1 |
| **Prompt universal (atual)** | ✅ LLM lê e entende o código | ✅ Novos tipos: só edite o `.txt` | **1** |

---

## 5. Baixar as Submissões do Moodle VPL

1. Acesse a atividade **VPL** no Moodle
2. Clique em **Lista de envios**
3. Localize a **seta para baixo** (⬇) no canto direito do cabeçalho da tabela
4. Clique em **Baixar todos os envios**
5. Descompacte o `.zip` e mova a pasta para o projeto:

**macOS / Linux:**
```bash
mv ~/Downloads/p1moodle1 ./p1moodle1
```

**Windows (PowerShell):**
```powershell
Move-Item "$env:USERPROFILE\Downloads\p1moodle1" .\p1moodle1
```

A estrutura resultante deve ser:

```
p1moodle1/
├── Sobrenome1 Nome1 - aluno.1/
│   ├── 2026-03-04-10-14-39/
│   │   ├── Q1.py
│   │   └── Q2.py
│   └── 2026-03-04-10-14-39.ceg/
│       └── execution.txt
└── ...
```

---

## 6. Executar a Correção com IA

### macOS / Linux

```bash
chmod +x runProvaNq.sh
./runProvaNq.sh p1moodle1
```

### Windows — Git Bash

```bash
bash runProvaNq.sh p1moodle1
```

### Windows — PowerShell (alternativa sem bash)

```powershell
python graderNq.py p1moodle1 config.yaml --max-concurrent 3
```

### Opções disponíveis

```
./runProvaNq.sh <pasta_alunos> [config.yaml] [--max-concurrent N]
```

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `pasta_alunos` | — | Pasta com as submissões (obrigatório) |
| `config.yaml` | `config.yaml` | Arquivo de configuração |
| `--max-concurrent N` | `3` | Chamadas simultâneas à API Groq |

Exemplos:
```bash
./runProvaNq.sh p1moodle1
./runProvaNq.sh p1moodle1 config.yaml
./runProvaNq.sh p1moodle1 config.yaml --max-concurrent 5
```

### O que acontece durante a execução

1. Valida o ambiente (Python, dependências, arquivos obrigatórios)
2. Para cada aluno, localiza a **última submissão** (pasta com timestamp mais recente)
3. Para cada questão (`Q1.py`, `Q2.py`, ...):
   - Envia o código + `prompt.txt` à API Groq
   - A LLM identifica o tipo da questão lendo o próprio código
   - A LLM avalia com a rubrica correspondente ao tipo identificado
   - Tudo em **uma única chamada por questão**
4. Todas as questões de todos os alunos são processadas **em paralelo**, respeitando o limite de concorrência
5. Se um modelo LLM falhar, tenta automaticamente o próximo da lista com backoff exponencial
6. Consolida todos os resultados em `p1moodle1_ALL.txt`

---

## 7. Estrutura do rubrica.txt

Cada aluno recebe um `rubrica.txt` com:

| Seção | Conteúdo |
|---|---|
| Cabeçalho | Nome do aluno, data de geração, questões e pesos |
| Correção Moodle | Nota extraída do `execution.txt` |
| Por questão | Código submetido + tipo identificado pela LLM + avaliação por critério |
| Resumo | Comparativo Moodle × IA por questão, com diferença em pontos |
| Log bruto Moodle | Saída completa do `execution.txt` |

E o consolidado geral em:

```
p1moodle1_ALL.txt
```

Para visualizar:

```bash
# macOS / Linux / Git Bash
cat p1moodle1_ALL.txt | less

# Windows (PowerShell)
Get-Content p1moodle1_ALL.txt | more
```

---

## 8. Gerar Planilha CSV com as Notas

O arquivo consolidado gerado pelo sistema (`*_ALL.txt`) contém todos os alunos e o resumo **Moodle × IA**.
Para facilitar análise em planilhas (Excel, LibreOffice, Google Sheets), é possível convertê-lo para **CSV**.

### Script de conversão

O projeto inclui o script:

```
gerar_relatorio.py
```

Ele extrai automaticamente:

* Nome do aluno
* Login
* Nota Moodle por questão
* Nota IA por questão
* Totais
* Diferença entre IA e Moodle

### Executar

```bash
python3 gerar_relatorio.py p1moodle1_ALL.txt
```

O script gera automaticamente:

```
p1moodle1_ALL.csv
```

ou seja, **o mesmo nome do arquivo de entrada, com extensão `.csv`**.

### Estrutura do CSV

O arquivo gerado possui as colunas:

| Coluna       | Descrição                          |
| ------------ | ---------------------------------- |
| Nome         | Nome completo do aluno             |
| Login        | Login Moodle                       |
| Q1_Moodle    | Nota da questão 1 segundo o Moodle |
| Q2_Moodle    | Nota da questão 2 segundo o Moodle |
| Total_Moodle | Soma das notas do Moodle           |
| Q1_IA        | Nota da questão 1 segundo a IA     |
| Q2_IA        | Nota da questão 2 segundo a IA     |
| Total_IA     | Soma das notas da IA               |
| Diferenca    | `Total_IA - Total_Moodle`          |


### Abrir no Excel / LibreOffice

* **Excel:** Arquivo → Abrir → selecione `*.csv`
* **LibreOffice Calc:** Arquivo → Abrir → delimitador `,`
* **Google Sheets:** Upload → selecione o CSV

Isso permite **ordenar alunos, filtrar discrepâncias entre IA e Moodle e gerar estatísticas da prova**.

---

## 9. Envio de Feedbacks por E-mail (Opcional)

O script `enviar_email.py` envia o `rubrica.txt` como anexo para cada aluno no endereço `login@aluno.ufabc.edu.br`.

### Configuração

1. Preencha a seção `email:` no `config.yaml` com suas credenciais SMTP
2. Preencha a seção `templates:` com assunto e corpo do e-mail

### Teste antes de enviar

No script, o endereço está redirecionado para um e-mail de teste:

```python
email_destino = 'fzampirolli@gmail.com'   # TESTE — comente para produção
```

Valide o conteúdo com seu próprio e-mail antes de disparar para todos os alunos.

### Executar

```bash
python3 enviar_email.py        # macOS / Linux
python  enviar_email.py        # Windows
```

> ⚠️ O e-mail enviado aos alunos deixa explícito que a correção é gerada por IA  
> e pode conter imprecisões. **A nota oficial sempre é a atribuída pelo professor no Moodle.**

---

## 10. Modelos LLM Disponíveis

Configurados em `config.yaml` na seção `groq.models`. O sistema tenta cada modelo em ordem e passa para o próximo em caso de falha:

| Modelo | Observação |
|---|---|
| `llama-3.3-70b-versatile` | Melhor qualidade geral |
| `openai/gpt-oss-120b` | Alta capacidade |
| `llama-3.1-8b-instant` | Mais rápido, menor qualidade |
| `openai/gpt-oss-20b` | Rápido |

O plano gratuito do Groq permite **30 requisições por minuto**. Consulte os limites atuais em [console.groq.com/settings/limits](https://console.groq.com/settings/limits).

---

## 11. Solução de Problemas

**`❌ Execute com bash: bash runProvaNq.sh`**  
No macOS/Linux execute `bash runProvaNq.sh p1moodle1`.  
No Windows use Git Bash ou chame diretamente: `python graderNq.py p1moodle1`.

**Nota Moodle aparece como `0.00` ou `N/A`**  
Verifique se existe `TIMESTAMP.ceg/execution.txt` na pasta do aluno.  
O sistema extrai a nota do padrão `Grade :=>>100` nesse arquivo.

**Tipo identificado como `DESCONHECIDO`**  
A LLM não reconheceu o tipo pelo código. Revise a seção de identificação no `prompt.txt` e adicione características mais precisas do tipo em questão.

**Nota da IA aparece como `?`**  
A resposta da LLM não contém uma linha de nota reconhecível.  
Certifique-se de que o `prompt.txt` instrui explicitamente:
```
Nota: X + Y + Z = TOTAL/PESO
```

**Arquivo de código não encontrado**  
Extensões suportadas: `.py`, `.java`, `.c`, `.cpp`, `.js`, `.ts`.  
Os arquivos devem estar diretamente na pasta de timestamp, nomeados `Q1.py`, `Q2.py`, etc.

**Erro HTTP 400 (`max_tokens`)**  
O `max_response_chars` no `config.yaml` excede o limite da Groq.  
O sistema já limita automaticamente a 8192 tokens — não é necessário ajustar.

**Windows: `python3` não reconhecido**  
No Windows o comando é `python` (sem o `3`). Use `python graderNq.py ...` diretamente.

---

## 12. Privacidade — O que é enviado à API Groq

A cada correção, o sistema envia à API Groq **apenas dois campos**:

| Campo | Conteúdo | Dado pessoal? |
|---|---|---|
| `system` | Conteúdo do `prompt.txt` (critérios de avaliação) | ❌ Não |
| `user` | Nome do arquivo (`Q1.py`) + código-fonte do aluno | ❌ Não |

**Nunca são enviados:** nome do aluno, e-mail, login, RA, CPF, turma ou qualquer outro metadado. Esses dados existem apenas como nomes de pastas locais e nunca são incluídos na requisição HTTP.

> ⚠️ **Única ressalva:** se o professor incluir dados identificadores dentro do `prompt.txt`,  
> esses dados serão transmitidos. O arquivo de prompt normalmente contém apenas critérios pedagógicos.

---

## 13. Segurança

O `config.yaml` contém sua API key e senha de e-mail. Ele já está no `.gitignore` do projeto, mas certifique-se de que o seu também contenha:

```
config.yaml
*.env
logs/
*_ALL.txt
```

Nunca compartilhe nem publique o `config.yaml`.