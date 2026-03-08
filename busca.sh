#!/usr/bin/env bash
# busca.sh - Verifica se as subpastas de submissão possuem o arquivo rubrica.txt
# ./busca.sh p1moodle

# Verifica se o parâmetro foi passado
if [ -z "$1" ]; then
    echo "Uso: $0 <nome_da_pasta>"
    echo "Exemplo: $0 p1moodle"
    exit 1
fi

PASTA_BASE="$1"

# Verifica se a pasta existe
if [ ! -d "$PASTA_BASE" ]; then
    echo "❌ Erro: A pasta '$PASTA_BASE' não existe."
    exit 1
fi

echo "🔍 Verificando subpastas em '$PASTA_BASE' sem rubrica.txt..."
echo "-----------------------------------------------------------"

# O contador ajuda a ter uma visão geral do progresso
count=0

for d in "$PASTA_BASE"/*/*/; do
    # Remove a barra final
    dir="${d%/}"
    
    # 1. Ignora pastas que terminam com .ceg (metadados do VPL/Moodle)
    if [[ "$dir" == *.ceg ]]; then
        continue
    fi

    # 2. Verifica se o arquivo rubrica.txt NÃO existe
    if [ ! -f "$dir/rubrica.txt" ]; then
        # Extrai o nome do aluno (ajustado para o parâmetro)
        aluno=$(echo "$dir" | cut -d'/' -f2)
        echo "❌ Faltando para: $aluno -> $dir"
        ((count++))
    fi
done

if [ $count -eq 0 ]; then
    echo "✅ Tudo em ordem! Todas as pastas de submissão possuem rubrica.txt."
else
    echo "-----------------------------------------------------------"
    echo "⚠️ Total de pastas pendentes: $count"
fi