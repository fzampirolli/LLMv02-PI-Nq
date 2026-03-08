#!/bin/bash

# Verifica argumento
if [ -z "$1" ]; then
  echo "Uso: $0 /caminho/para/a/pasta"
  exit 1
fi

PASTA="$1"

for d in "$PASTA"/*/; do
  dir_name=$(basename "$d")

  # Separa os campos por espaço
  IFS=' ' read -ra partes <<< "$dir_name"

  num_partes=${#partes[@]}
  if (( num_partes < 4 )); then
    echo "Pasta ignorada (muito curta): $dir_name"
    continue
  fi

  usuario="${partes[$((num_partes-1))]}"
  ra="${partes[$((num_partes-2))]}"
  primeiro_nome="${partes[$((num_partes-3))]}"

  # Pega os demais nomes (do início até antes do primeiro_nome)
  restante_nome=""
  for ((i=0; i<num_partes-3; i++)); do
    restante_nome+="${partes[$i]} "
  done
  restante_nome=$(echo "$restante_nome" | sed 's/ *$//') # remove espaço final

  novo_nome="${primeiro_nome} ${restante_nome} - ${usuario}"
  novo_path="${PASTA}/${novo_nome}"

  mv "$d" "$novo_path"
  echo "Renomeado: '$dir_name' → '$novo_nome'"
done
