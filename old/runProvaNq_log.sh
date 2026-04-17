#!/bin/bash
# bash ./runProvaNq_log.sh p1moodle0

LOG_FILE="p3moodle_log_$(date +%Y%m%d_%H%M).txt"
START_TIME=$SECONDS

echo "Iniciando processamento em: $(date)" | tee -a "$LOG_FILE"

# Executa o script original enviando tudo para o log e para a tela
bash ./runProvaNq.sh p3moodle/ 2>&1 | tee -a "$LOG_FILE"

ELAPSED=$((SECONDS - START_TIME))
FINAL_MSG="
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEMPO TOTAL DE PROCESSAMENTO: $(($ELAPSED / 60))m $(($ELAPSED % 60))s
FINALIZADO EM: $(date)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "$FINAL_MSG" | tee -a "$LOG_FILE"
