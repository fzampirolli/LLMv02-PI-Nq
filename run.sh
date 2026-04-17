#!/bin/bash

# run.sh - Script de execução simplificado
# Uso: bash run.sh [config.yaml] [--log]

# 1. Define qual arquivo de configuração usar (padrão é config.yaml)
CONFIG_FILE=${1:-config.yaml}
LOG_ENABLED=false
START_TOTAL=$SECONDS #

# 2. Verifica se o arquivo de configuração existe
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Erro: Arquivo de configuração '$CONFIG_FILE' não encontrado!"
    exit 1
fi

# 3. Verifica se o usuário pediu log
for arg in "$@"; do
    if [ "$arg" == "--log" ]; then
        LOG_ENABLED=true
    fi
done

# 4. Extrai o diretório base dinamicamente do arquivo de configuração
STUDENT_DIR=$(grep 'student_base_dir:' "$CONFIG_FILE" | awk -F': ' '{print $2}' | tr -d '"' | tr -d "'" | xargs)

# 5. Validação
if [ -z "$STUDENT_DIR" ]; then
    echo "❌ Erro: Não foi possível encontrar 'student_base_dir' em $CONFIG_FILE"
    exit 1
fi

echo "------------------------------------------------"
echo "  SISTEMA DE CORREÇÃO AUTOMÁTICA REENGENHARIA   "
echo "------------------------------------------------"
echo "📂 Pasta de alunos: $STUDENT_DIR"
echo "⚙️  Configuração: $CONFIG_FILE"
echo "⏰ Início: $(date)"

# 6. Execução do Python com medição de tempo
LOG_NAME="log_correcao_$(date +%Y%m%d_%H%M).txt"

if [ "$LOG_ENABLED" = true ]; then
    echo "📝 Modo Log Ativado: Gravando em $LOG_NAME"
    # O Python já processa os alunos; o tempo individual é melhor logado dentro do main.py
    # Mas aqui medimos o bloco principal de execução
    python3 main.py --config "$CONFIG_FILE" 2>&1 | tee "$LOG_NAME"
else
    python3 main.py --config "$CONFIG_FILE"
fi

# 7. Cálculo de tempo total
ELAPSED_TOTAL=$((SECONDS - START_TOTAL))
M=$((ELAPSED_TOTAL / 60))
S=$((ELAPSED_TOTAL % 60))

# 8. Geração do arquivo consolidado
echo ""
echo "------------------------------------------------"
echo "📂 Gerando arquivo consolidado ${STUDENT_DIR}_ALL.txt..."

rm "${STUDENT_DIR}_ALL.txt" 2>/dev/null

# Conta os alunos (pastas) excluindo a pasta raiz
NUM_ALUNOS=$(find "$STUDENT_DIR" -maxdepth 1 -type d | wc -l)
NUM_ALUNOS=$((NUM_ALUNOS - 1))

find "$STUDENT_DIR" -name "rubrica.txt" | sort | while read -r arquivo; do
    echo "================================================================================"
    echo "ALUNO: $arquivo"
    echo "================================================================================"
    cat "$arquivo"
    echo -e "\n\n"
done > "${STUDENT_DIR}_ALL.txt"

echo "✅ Arquivo consolidado gerado com sucesso!"

# 9. Bloco de Estatísticas (Enviado para o log se habilitado)
FINAL_STATS="
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ESTATÍSTICAS DE PROCESSAMENTO:
   Tempo Total: ${M}m ${S}s"

if [ "$NUM_ALUNOS" -gt 0 ]; then
    TEMPO_MEDIO=$((ELAPSED_TOTAL / NUM_ALUNOS))
    FINAL_STATS="$FINAL_STATS
   Tempo Médio por Aluno: ~${TEMPO_MEDIO}s"
fi

FINAL_STATS="$FINAL_STATS
   Finalizado em: $(date)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Exibe na tela e, se o log estiver ativo, anexa ao arquivo
echo "$FINAL_STATS"
if [ "$LOG_ENABLED" = true ]; then
    echo "$FINAL_STATS" >> "$LOG_NAME"
fi

echo ""
echo "  cat ${STUDENT_DIR}_ALL.txt | less"