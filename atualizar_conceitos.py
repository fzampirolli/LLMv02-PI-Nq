"""
Atualiza os conceitos do XLS com os dados do CSV.
- Remove +/- dos conceitos (ex: D+ -> D)
- Faz match por nome normalizado (sem acentos, case-insensitive)
- Preserva formatação original do XLS

Uso:
  python3 atualizar_conceitos.py notas.xls Prova1_submissions.csv
  python3 atualizar_conceitos.py notas.xls Prova1_submissions.csv -o resultado.xls

Dependências: pip install "xlrd==1.2.0" xlwt xlutils
"""

import re
import sys
import argparse
import unicodedata
import subprocess
from pathlib import Path
from typing import Optional


# ── Instala dependências automaticamente se necessário ──────────────────────
def ensure(pkg, import_as=None):
    try:
        __import__(import_as or pkg)
    except ImportError:
        print(f"Instalando {pkg}...")
        ret = subprocess.call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            stderr=subprocess.DEVNULL
        )
        if ret != 0:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q",
                 "--break-system-packages"]
            )

ensure("xlrd==1.2.0", "xlrd")
ensure("xlwt", "xlwt")
ensure("xlutils", "xlutils")

import xlrd
import xlwt
import pandas as pd
from xlutils.copy import copy as xl_copy


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return name.upper().strip()


def extract_concept(nota: str) -> Optional[str]:
    match = re.search(r"\(([A-F][+-]?)\)", str(nota))
    if match:
        return re.sub(r"[+-]", "", match.group(1))
    return None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Atualiza conceitos do XLS com dados do CSV."
    )
    parser.add_argument("xls", help="Arquivo XLS de notas (ex: notas_turma.xls)")
    parser.add_argument("csv", help="Arquivo CSV com submissões (ex: Prova1_submissions.csv)")
    parser.add_argument("-o", "--output", help="Arquivo de saída (padrão: notas_atualizado.xls)",
                        default="notas_atualizado.xls")
    return parser.parse_args()


def main():
    args = parse_args()

    xls_input = Path(args.xls)
    csv_input = Path(args.csv)
    output    = Path(args.output)

    if not xls_input.exists():
        print(f"ERRO: arquivo XLS não encontrado: {xls_input}")
        sys.exit(1)
    if not csv_input.exists():
        print(f"ERRO: arquivo CSV não encontrado: {csv_input}")
        sys.exit(1)

    print(f"XLS: {xls_input.name}")
    print(f"CSV: {csv_input.name}")

    # 1. Carregar CSV e montar dicionário nome -> conceito
    csv = pd.read_csv(csv_input)
    conceitos = {}
    for _, row in csv.iterrows():
        nome = normalize(str(row["Unnamed: 2"]))
        conceito = extract_concept(str(row["Nota"]))
        if conceito:
            conceitos[nome] = conceito

    print(f"Conceitos carregados do CSV: {len(conceitos)}")

    # 2. Abrir XLS original com xlrd
    rb = xlrd.open_workbook(str(xls_input), formatting_info=True)
    ws_r = rb.sheet_by_index(0)

    # 3. Criar cópia editável com xlutils
    wb = xl_copy(rb)
    ws_w = wb.get_sheet(0)

    # 4. Localizar linha de cabeçalho e colunas
    header_row = col_nome = col_resultado = None
    for row_idx in range(ws_r.nrows):
        for col_idx in range(ws_r.ncols):
            val = str(ws_r.cell_value(row_idx, col_idx)).strip()
            if val == "Matrícula":
                header_row = row_idx
            if val == "Nome":
                col_nome = col_idx
            if val == "Resultado":
                col_resultado = col_idx
        if header_row is not None and col_nome is not None and col_resultado is not None:
            break

    if header_row is None or col_nome is None or col_resultado is None:
        print("ERRO: cabeçalho não encontrado no XLS.")
        sys.exit(1)

    # 5. Iterar alunos e atualizar conceitos
    atualizados = []
    nao_encontrados = []

    for row_idx in range(header_row + 1, ws_r.nrows):
        nome_val = str(ws_r.cell_value(row_idx, col_nome)).strip()
        if not nome_val:
            continue

        nome_norm = normalize(nome_val)
        if nome_norm in conceitos:
            conceito = conceitos[nome_norm]
            ws_w.write(row_idx, col_resultado, conceito)
            atualizados.append(f"  {nome_val} -> {conceito}")
        else:
            nao_encontrados.append(f"  {nome_val}")

    # 6. Salvar
    wb.save(str(output))

    print(f"\n✅ Atualizados ({len(atualizados)}):")
    print("\n".join(atualizados))

    if nao_encontrados:
        print(f"\n⚠️  Não encontrados no CSV ({len(nao_encontrados)}):")
        print("\n".join(nao_encontrados))

    print(f"\nArquivo salvo em: {output}")


if __name__ == "__main__":
    main()