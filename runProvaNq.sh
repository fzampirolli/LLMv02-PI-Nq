#!/usr/bin/env bash
# =============================================================================
#  runProvaNq.sh — Correção automática de provas com N questões (Moodle VPL)
#
#  Uso:
#    bash runProvaNq.sh <pasta_alunos> [config.yaml] [--max-concurrent N]
#
#  Exemplos:
#    bash runProvaNq.sh Prova1
#    bash runProvaNq.sh Prova1 config.yaml
#    bash runProvaNq.sh Prova1 config.yaml --max-concurrent 5
#
#  Estrutura esperada:
#    Prova1/
#    ├── Nome Aluno - login/
#    │   ├── 2026-03-04-10-14-39/        ← última submissão (timestamp)
#    │   │   ├── Q1.py                   ← código questão 1
#    │   │   └── Q2.py                   ← código questão 2
#    │   └── 2026-03-04-10-14-39.ceg/
#    │       └── execution.txt
#    └── ...
#
#  O tipo de cada questão (A ou B) é detectado automaticamente pelo conteúdo
#  do código. O prompt correto (ex. prompt.txt) é selecionado
#  e enviado à API Groq junto com o código do aluno.
# =============================================================================

[ -z "${BASH_VERSION:-}" ] && { echo "❌ Execute com bash: bash $0 $*" >&2; exit 1; }

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Cores ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Correção Automática de Provas — N Questões (IA)        ║"
echo "║   A LLM identifica o tipo e avalia em uma única chamada  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  Início : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Argumentos ────────────────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
    echo -e "${RED}Uso: bash $0 <pasta_alunos> [config.yaml] [--max-concurrent N]${RESET}"
    echo ""
    echo "  Exemplos:"
    echo "    bash $0 Prova1"
    echo "    bash $0 Prova1 config.yaml"
    echo "    bash $0 Prova1 config.yaml --max-concurrent 5"
    exit 1
fi

STUDENT_DIR="$1"
CONFIG_FILE="${2:-config.yaml}"
MAX_CONCURRENT=3

# Captura --max-concurrent em qualquer posição
NEXT_IS_CONC=false
for arg in "$@"; do
    if $NEXT_IS_CONC; then
        MAX_CONCURRENT="$arg"
        NEXT_IS_CONC=false
    elif [ "$arg" = "--max-concurrent" ]; then
        NEXT_IS_CONC=true
    fi
done

# ── Validações ────────────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Validando ambiente...${RESET}"

# Python
if   command -v python3 &>/dev/null; then PYTHON=python3
elif command -v python  &>/dev/null; then PYTHON=python
else
    echo -e "${RED}❌ Python não encontrado. Instale Python 3.8+.${RESET}"; exit 1
fi
echo -e "  ${GREEN}✓${RESET} $($PYTHON --version 2>&1)"

# Dependências Python
for pkg in aiohttp yaml; do
    if ! $PYTHON -c "import $pkg" 2>/dev/null; then
        echo -e "${RED}❌ Dependência ausente: $pkg${RESET}"
        echo -e "   Instale com: pip install aiohttp pyyaml"
        exit 1
    fi
done
echo -e "  ${GREEN}✓${RESET} Dependências Python OK (aiohttp, pyyaml)"

# Arquivos obrigatórios
for f in "$CONFIG_FILE" "graderNq.py" "llm_interface_prova.py" "prompt.txt"; do
    if [ ! -f "$SCRIPT_DIR/$f" ]; then
        echo -e "${RED}❌ Arquivo não encontrado: $f${RESET}"; exit 1
    fi
done
echo -e "  ${GREEN}✓${RESET} Arquivos do projeto OK (graderNq.py, prompt.txt — universal)"

# Pasta de alunos
if [ ! -d "$SCRIPT_DIR/$STUDENT_DIR" ]; then
    echo -e "${RED}❌ Pasta não encontrada: $STUDENT_DIR${RESET}"; exit 1
fi
NALUNOS=$(find "$SCRIPT_DIR/$STUDENT_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
echo -e "  ${GREEN}✓${RESET} Pasta '$STUDENT_DIR' encontrada — $NALUNOS pasta(s) de aluno(s)"

# Lock
LOCKFILE="/tmp/runProvaNq_$(echo "$STUDENT_DIR" | tr '/. ' '___').lock"
if [ -f "$LOCKFILE" ]; then
    echo -e "${YELLOW}⚠ Já existe uma execução em andamento para '$STUDENT_DIR'.${RESET}"
    echo -e "  Se não houver outro processo ativo, remova: $LOCKFILE"
    exit 1
fi
touch "$LOCKFILE"
trap "rm -f '$LOCKFILE'" EXIT

echo ""
echo -e "${BOLD}[2/5] Configuração${RESET}"
echo -e "  Pasta        : $STUDENT_DIR"
echo -e "  Config       : $CONFIG_FILE"
echo -e "  Concorrência : $MAX_CONCURRENT chamadas simultâneas"
echo ""

# ── Execução ──────────────────────────────────────────────────────────────────
echo -e "${BOLD}[3/5] Iniciando correção...${RESET}"
echo ""

cd "$SCRIPT_DIR"
$PYTHON graderNq.py "$STUDENT_DIR" "$CONFIG_FILE" --max-concurrent "$MAX_CONCURRENT"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${BOLD}[4/5] Correção concluída.${RESET}"

    ALL_FILE="${STUDENT_DIR}_ALL.txt"
    if [ -f "$ALL_FILE" ]; then
        NRUBRICAS=$(grep -c "ALUNO:" "$ALL_FILE" 2>/dev/null || echo "?")
        echo -e "  ${GREEN}✓${RESET} Consolidado  : $ALL_FILE"
        echo -e "  ${GREEN}✓${RESET} Processados  : $NRUBRICAS aluno(s)"
    fi

    echo ""
    echo -e "${BOLD}[5/5] Próximos passos${RESET}"
    echo -e "  cat ${STUDENT_DIR}_ALL.txt | less   # ver todos os resultados"
    echo -e "  python3 enviar_email.py             # enviar feedbacks (opcional)"
else
    echo -e "${RED}[4/5] ❌ Execução encerrada com erro (código $EXIT_CODE).${RESET}"
    exit $EXIT_CODE
fi

echo ""
echo -e "  Fim : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""