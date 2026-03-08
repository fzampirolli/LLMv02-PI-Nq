import re
import csv
import os
import sys


def extrair_dados(caminho_arquivo):

    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    # separa blocos de alunos
    blocos = re.split(r'═{10,}', conteudo)

    lista_alunos = []

    for bloco in blocos:

        if "ALUNO" not in bloco:
            continue

        match_id = re.search(r'ALUNO\s*:\s*(.*?)\s*-\s*([^\s│]*)', bloco)

        if not match_id:
            continue

        nome = match_id.group(1).strip()
        login = match_id.group(2).strip()

        # Moodle
        q1_m_match = re.search(
            r'-Question 1:.*?Avaliação:.*?\(([\d.]+)%\)',
            bloco,
            re.DOTALL
        )

        q2_m_match = re.search(
            r'-Question 2:.*?Avaliação:.*?\(([\d.]+)%\)',
            bloco,
            re.DOTALL
        )

        q1_moodle = float(q1_m_match.group(1)) * 0.5 if q1_m_match else 0
        q2_moodle = float(q2_m_match.group(1)) * 0.5 if q2_m_match else 0
        total_moodle = q1_moodle + q2_moodle

        # IA
        q1_ia_match = re.search(r'Q1 \(IA.*?\)\s*:\s*([\d.]+)\s*/\s*50', bloco)
        q2_ia_match = re.search(r'Q2 \(IA.*?\)\s*:\s*([\d.]+)\s*/\s*50', bloco)

        q1_ia = float(q1_ia_match.group(1)) if q1_ia_match else 0
        q2_ia = float(q2_ia_match.group(1)) if q2_ia_match else 0
        total_ia = q1_ia + q2_ia

        lista_alunos.append({
            "Nome": nome,
            "Login": login,
            "Q1_Moodle": f"{q1_moodle:.2f}",
            "Q2_Moodle": f"{q2_moodle:.2f}",
            "Total_Moodle": f"{total_moodle:.2f}",
            "Q1_IA": f"{q1_ia:.2f}",
            "Q2_IA": f"{q2_ia:.2f}",
            "Total_IA": f"{total_ia:.2f}",
            "Diferenca": f"{(total_ia - total_moodle):.2f}",
        })

    lista_alunos.sort(key=lambda x: x["Nome"])

    return lista_alunos


def salvar_csv(dados, arquivo_saida):

    header = [
        "Nome",
        "Login",
        "Q1_Moodle",
        "Q2_Moodle",
        "Total_Moodle",
        "Q1_IA",
        "Q2_IA",
        "Total_IA",
        "Diferenca",
    ]

    with open(arquivo_saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(dados)


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Uso: python3 gerar_relatorio.py arquivo.txt")
        sys.exit(1)

    entrada = sys.argv[1]

    # gera nome do csv automaticamente
    base = os.path.splitext(entrada)[0]
    saida = base + ".csv"

    dados = extrair_dados(entrada)
    salvar_csv(dados, saida)

    print(f"✅ {len(dados)} alunos exportados para {saida}")