import asyncio
import logging
import re
import csv
from pathlib import Path
from typing import Dict, List, Optional

from .utils import (
    extrair_nota_ia, find_latest_submission, get_code_content,
    extrair_dados_vpl, extrair_execucao_vpl_por_questao,
    extrair_enunciado_vpl_por_questao,   # NOVO
)

logger = logging.getLogger(__name__)

W = 96

def _t(): return "┌" + "─" * W + "┐"
def _b(): return "└" + "─" * W + "┘"
def _s(): return "├" + "─" * W + "┤"

def _r(s):
    s = str(s).replace('\n', ' ').strip()
    return "│ " + s.ljust(W - 2)[:W-2] + " │"


def formatar_texto_IA(texto, W=80):
    def quebra_linha(linha, W):
        indent = len(linha) - len(linha.lstrip())
        prefixo = inline_prefix = linha[:indent]
        conteudo = linha.strip()

        bullet = ""
        if conteudo.startswith(("- ", "* ")):
            bullet = conteudo[:2]
            conteudo = conteudo[2:]
            prefixo += bullet
            indent_extra = " " * len(bullet)
        else:
            indent_extra = ""

        palavras = conteudo.split()
        linhas = []
        atual = prefixo

        for p in palavras:
            if len(atual) + len(p) + 1 <= W:
                if atual.strip() == "":
                    atual += p
                else:
                    atual += " " + p
            else:
                linhas.append(atual)
                atual = " " * indent + indent_extra + p

        if atual:
            linhas.append(atual)

        return linhas

    resultado = []
    for line in texto.split("\n"):
        if line.strip() == "":
            resultado.append("")
        else:
            resultado.extend(quebra_linha(line, W))

    return "\n".join(resultado)

async def process_student(student_path: Path, client, config: Dict, semaphore: asyncio.Semaphore):
    async with semaphore:
        student_name = student_path.name
        login = student_name.split(" - ")[-1] if " - " in student_name else student_name
        
        sub_dir = find_latest_submission(student_path)
        if not sub_dir: 
            return None

        rubric_name = config['paths'].get('output_rubric_filename', 'rubrica.txt')
        rubric_path = sub_dir / rubric_name
        weights = config['grading']['weights']
        total_peso = sum(weights.values())

        full_content = ""
        moodle_data = extrair_dados_vpl(sub_dir, weights)
        ia_parciais = {k: 0.0 for k in weights.keys()}

        # --- LÓGICA DE CACHE ---
        if rubric_path.exists():
            try:
                full_content = rubric_path.read_text(encoding='utf-8')
                tipos_cache: Dict[str, str] = {}
                confiancas_cache: Dict[str, str] = {}
                for q_key in weights.keys():
                    padrao = rf"{q_key.upper()}\s*\(IA\)\s*:\s*([\d.]+)"
                    match = re.search(padrao, full_content, re.IGNORECASE)
                    if match:
                        ia_parciais[q_key] = float(match.group(1))

                    q_num_cache = int(''.join(filter(str.isdigit, q_key)))
                    m_tipo_cache = re.search(
                        rf"AVALIAÇÃO TIPO\s*([ABC][0-9]?)\s*-\s*Q{q_num_cache}\b",
                        full_content
                    )
                    tipos_cache[q_key] = m_tipo_cache.group(1) if m_tipo_cache else "N/A"

                    # A confiança aparece na linha logo após o cabeçalho acima
                    m_conf_cache = re.search(
                        rf"AVALIAÇÃO TIPO\s*[ABC][0-9]?\s*-\s*Q{q_num_cache}[^\n]*\n[^\n]*Confiança[^:]*:\s*([^\n│]+)",
                        full_content
                    )
                    confiancas_cache[q_key] = m_conf_cache.group(1).strip() if m_conf_cache else "N/A"

                ia_total = sum(ia_parciais.values())
                logger.info(f"  ⏭️  {student_name}: Usando cache local.")
                return {
                    "status": "ok",
                    "student": student_name,
                    "login": login,
                    "content": full_content,
                    "moodle_parciais": moodle_data['parciais'],
                    "ia_parciais": ia_parciais,
                    "moodle_total": moodle_data['total'],
                    "ia_total": ia_total,
                    "diff": ia_total - moodle_data['total'],
                    "tipos_detectados": tipos_cache,
                    "confiancas": confiancas_cache
                }
            except Exception as e:
                logger.warning(f"  ⚠️ Erro ao ler cache de {student_name}, reavaliando: {e}")

        # --- NOVA CONSULTA (API) ---
        logger.info(f"  🤖 {student_name}: Consultando API...")
        ia_blocks = []
        prompt_path = Path(config['grading']['prompt_file'])
        system_prompt = prompt_path.read_text(encoding='utf-8')
        extensions = config['grading'].get('supported_extensions', ['py', 'java', 'cpp'])

        questoes_avaliadas = set()
        questoes_com_codigo = set()
        tipos_detectados: Dict[str, str] = {}
        confiancas: Dict[str, str] = {}

        # NOVO: resultado real de execução do VPL (input/saída do aluno/saída esperada)
        # extraído uma única vez para todas as questões deste aluno.
        vpl_execucao = extrair_execucao_vpl_por_questao(sub_dir, weights)
        vpl_enunciados = extrair_enunciado_vpl_por_questao(sub_dir, weights)

        # NOVO: pré-carrega o código de TODAS as questões, para poder oferecer
        # os demais códigos como contexto (ajuda a IA a perceber o padrão de
        # estilo do aluno e a identificar corretamente o tipo sorteado de cada
        # questão), mesmo que a nota final ainda seja calculada por questão.
        codigos_por_questao = {}
        for q_key in weights.keys():
            q_num_tmp = int(''.join(filter(str.isdigit, q_key)))
            codigos_por_questao[q_key] = get_code_content(sub_dir, q_num_tmp, extensions)

        for q_key, weight in weights.items():
            q_num = int(''.join(filter(str.isdigit, q_key)))
            code = codigos_por_questao.get(q_key)
            
            if not code:
                ia_parciais[q_key] = 0.0
                continue

            questoes_com_codigo.add(q_key)

            # --- Monta o conteúdo enriquecido enviado à LLM ---
            partes_user = [f"CÓDIGO DO ALUNO — Q{q_num} (avalie APENAS esta questão):\n{code}"]

            # NOVO: enunciado oficial da questão sorteada (fonte primária p/ tipo)
            enunciado_oficial = vpl_enunciados.get(q_key, "").strip()
            if enunciado_oficial:
                partes_user.append(
                    "\n\n=== ENUNCIADO OFICIAL DA QUESTÃO Q" + str(q_num) + " (Moodle VPL) ===\n"
                    "Este é o texto exato da questão sorteada para este aluno, extraído "
                    "diretamente do Moodle/VPL. Use-o como evidência PRIMÁRIA para decidir "
                    "a linha \"Tipo identificado\" (inclusive entre C1/C2/C3 e entre "
                    "plana/pesos/cv2), mesmo que o código esteja incompleto ou ambíguo. "
                    "Se o código implementado divergir do que este enunciado pede, mantenha "
                    "o tipo conforme o ENUNCIADO (não conforme o código), rebaixe a "
                    "Confiança para Baixa e explique a divergência no feedback ao aluno.\n\n"
                    f"{enunciado_oficial}"
                )

            execucao_real = vpl_execucao.get(q_key, "").strip()
            nota_moodle_questao = moodle_data['parciais'].get(q_key, 0.0)
            if execucao_real:
                partes_user.append(
                    "\n\n=== RESULTADO REAL DA EXECUÇÃO NO VPL/MOODLE (Q" + str(q_num) + ") ===\n"
                    "Os testes automáticos abaixo foram executados de fato sobre o código "
                    "acima. Use isso como evidência objetiva de corretude — não como um "
                    "gabarito a ser copiado cegamente, mas para confirmar ou refutar sua "
                    "própria leitura da lógica antes de pontuar os Critérios 2 e 3. Se a "
                    "saída produzida bateu com a esperada em todos os testes, não hesite em "
                    "dar crédito pleno mesmo que o estilo de código seja incomum. Se houve "
                    "divergência, use o input/saída/esperado para apontar exatamente onde a "
                    "lógica do aluno está errada.\n"
                    f"Nota atribuída pelo VPL nesta questão: {nota_moodle_questao:.1f}/{weight} pts\n\n"
                    f"{execucao_real}"
                )

            outras_questoes = [
                (k, c) for k, c in codigos_por_questao.items() if k != q_key and c
            ]
            if outras_questoes:
                bloco_outras = "\n\n".join(
                    f"--- Q{int(''.join(filter(str.isdigit, k)))} (contexto apenas, NÃO avalie) ---\n{c}"
                    for k, c in outras_questoes
                )
                partes_user.append(
                    "\n\n=== OUTROS CÓDIGOS DO MESMO ALUNO NESTA PROVA (apenas contexto de "
                    "estilo; não pontue estes, avalie somente a Q" + str(q_num) + " acima) ===\n"
                    + bloco_outras
                )

            user_content = "\n".join(partes_user)

            response = await client.chat_completion(system_prompt, user_content)

            if response.success:
                questoes_avaliadas.add(q_key)
                
            nota_extraida = extrair_nota_ia(response.content, weight) if response.success else "0"
            try:
                nota = float(nota_extraida) if nota_extraida != "?" else 0.0
            except ValueError:
                nota = 0.0

            ia_parciais[q_key] = nota
            tipo_detectado = None
            confianca = "N/A"

            if response.success:
                # --- 1) FONTE PRIMÁRIA: linha estruturada que o prompt exige ---
                # Ex.: "Tipo identificado: TIPO C2 (Abertura — com pesos)"
                m_tipo = re.search(
                    r'Tipo\s+identificado\s*:\s*TIPO\s*([ABC][0-9]?)',
                    response.content, re.IGNORECASE
                )
                if m_tipo:
                    tipo_label = m_tipo.group(1).upper()   # ex: 'A', 'B', 'C1', 'C2', 'C3'
                    tipo_detectado = tipo_label[0]          # rubricas do prompt só têm A/B/C
                else:
                    tipo_label = None

                # --- 2) CONFIANÇA declarada pela IA (se o prompt pedir essa linha) ---
                m_conf = re.search(
                    r'Confian[çc]a\s*:\s*(Alta|M[eé]dia|Baixa)\b(.*)',
                    response.content, re.IGNORECASE
                )
                if m_conf:
                    confianca = m_conf.group(1).capitalize()
                    detalhe_conf = m_conf.group(2).strip(" -—:")
                    if detalhe_conf:
                        confianca += f" ({detalhe_conf[:120]})"

                # --- 3) FALLBACK: heurística antiga por palavra-chave ---
                # Só é usada se a IA não seguiu o formato pedido. Fica sinalizado
                # como baixa confiança para facilitar revisão manual depois.
                if tipo_detectado is None:
                    logger.warning(
                        f"  ⚠️ {student_name} Q{q_num}: linha 'Tipo identificado' não "
                        f"encontrada na resposta da IA — usando heurística de fallback."
                    )
                    conteudo_minusculo = response.content.lower()
                    if "limiarização" in conteudo_minusculo or "otsu" in conteudo_minusculo:
                        tipo_detectado = "A"
                    elif "1d" in conteudo_minusculo or "sinal" in conteudo_minusculo or "sinais" in conteudo_minusculo:
                        tipo_detectado = "B"
                    else:
                        tipo_detectado = "C"
                    tipo_label = tipo_detectado
                    if confianca == "N/A":
                        confianca = "Baixa (fallback heurístico — revisar manualmente)"

                tipos_detectados[q_key] = tipo_label
                confiancas[q_key] = confianca

                regex_rubrica = rf"\[START_RUBRICA_TIPO_{tipo_detectado}\](.*?)\[END_RUBRICA_TIPO_{tipo_detectado}\]"
                match_rubrica = re.search(regex_rubrica, system_prompt, re.DOTALL)

                if match_rubrica:
                    rubrica_texto = match_rubrica.group(1).strip()
                else:
                    rubrica_texto = f"AVISO: Critérios para TIPO '{tipo_detectado}' não encontrados no arquivo de prompt."
                
                clean_content = re.sub(r'(?:Tipo identificado|TIPO|IPO)\s*:?\s*([A-Z0-9]+)', '', response.content).strip()

                ia_blocks.append(_t())
                ia_blocks.append(_r(f"Q{q_num} - ENUNCIADO E CÓDIGO DO ALUNO"))
                ia_blocks.append(_s())
                ia_blocks.append("")
                if enunciado_oficial:
                    ia_blocks.append("ENUNCIADO DA QUESTÃO (extraído do VPL/Moodle):")
                    ia_blocks.append(formatar_texto_IA(enunciado_oficial, W))
                    ia_blocks.append("")
                    ia_blocks.append("CÓDIGO SUBMETIDO:")
                    ia_blocks.append("-" * len("CÓDIGO SUBMETIDO:"))
                ia_blocks.append(code)
                ia_blocks.append("")
                if execucao_real:
                    ia_blocks.append(_r("ℹ️  Evidência real de execução do VPL foi enviada à IA nesta avaliação."))
                    ia_blocks.append("")

                linhas_rubrica = rubrica_texto.splitlines()
                if linhas_rubrica:
                    ia_blocks.append("")
                    ia_blocks.append(linhas_rubrica[0])
                    ia_blocks.append("-" * len(linhas_rubrica[0]))
                    ia_blocks.extend(linhas_rubrica[1:])
                    ia_blocks.append("")

                ia_blocks.append(_s())
                ia_blocks.append(_r(f"AVALIAÇÃO TIPO {tipo_label} - Q{q_num} (Peso {weight} pts)"))
                ia_blocks.append(_r(f"Confiança na identificação do tipo: {confianca}"))
                ia_blocks.append(_s())

                ia_blocks.append("")
                ia_blocks.append(formatar_texto_IA(clean_content, W))
                ia_blocks.append("")
                
                ia_blocks.append(_b())
                ia_blocks.append("")

        # --- CÁLCULO PRECISO DO TOTAL SUCEDIDO ---
        ia_total = sum(ia_parciais.values())
        diff = ia_total - moodle_data['total']
                
        modelo_nome = response.model_used if 'response' in locals() and hasattr(response, 'model_used') else config.get('llm', {}).get('provider', 'IA').upper()

        resumo = []
        resumo.append(_t())
        resumo.append(_r(f"RESUMO — IA ({modelo_nome})  x  MOODLE"))
        resumo.append(_s())
        resumo.append(_r(f"Peso total : {total_peso} pts"))
        resumo.append(_r("─" * (W-2)))

        for q_key, w in weights.items():
            nota_ia = ia_parciais.get(q_key, 0.0)
            resumo.append(_r(f"{q_key.upper()} (IA) : {nota_ia:>4.1f} / {w} pts"))

        resumo.append(_r("─" * (W-2)))
        m_parts = " + ".join([f"{k.upper()}={v:.0f}" for k, v in moodle_data['parciais'].items()])
        resumo.append(_r(f"Moodle : ({m_parts}) = {moodle_data['total']:.0f} pts"))
        resumo.append(_r(f"IA     : {ia_total:.1f} / {total_peso} pts"))
        resumo.append(_r("─" * (W-2)))
        resumo.append(_r(f"Diferença (IA - Moodle): {diff:>+5.1f} pts"))
        resumo.append(_r("─" * (W-2)))
        for q_key in weights.keys():
            tipo_q = tipos_detectados.get(q_key, "N/A")
            conf_q = confiancas.get(q_key, "N/A")
            alerta = " ⚠️ REVISAR" if "fallback" in conf_q.lower() or "baixa" in conf_q.lower() else ""
            resumo.append(_r(f"{q_key.upper()}: tipo identificado = {tipo_q} | confiança = {conf_q}{alerta}"))
        resumo.append(_b())

        full_content = "\n".join(resumo) + "\n" + "\n".join(ia_blocks)

        if questoes_avaliadas == questoes_com_codigo:
            rubric_path.write_text(full_content, encoding='utf-8')
        else:
            faltando = questoes_com_codigo - questoes_avaliadas
            logger.warning(f"  ⚠️ {student_name}: IA falhou em {faltando}. rubrica.txt NÃO foi salvo.")
            
        return {
            "status": "ok",
            "student": student_name,
            "login": login,
            "content": full_content,
            "moodle_parciais": moodle_data['parciais'],
            "ia_parciais": ia_parciais,
            "moodle_total": moodle_data['total'],
            "ia_total": ia_total,
            "diff": diff,
            "tipos_detectados": tipos_detectados,
            "confiancas": confiancas
        }
    
def save_consolidated_report(results: List[Dict], output_path: Path):
    """
    Gera o arquivo ALL.txt consolidando o conteúdo de todos os alunos.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for r in results:
            if r and r.get("status") == "ok":
                f.write(r.get("content", ""))
                f.write("\n" + "═"*80 + "\n\n")

def save_csv_report(results: List[Dict], output_path: Path):
    """
    Gera uma planilha CSV comparando detalhadamente as notas do Moodle com a IA.
    """
    if not results:
        return

    # Filtra apenas os resultados válidos
    valid_results = [r for r in results if r and r.get("status") == "ok"]
    if not valid_results:
        return

    # Descobre dinamicamente as chaves das questões (ex: q1, q2, q3)
    sample = valid_results[0]
    q_keys = sorted(sample["moodle_parciais"].keys())

    headers = ["Aluno", "Login"]
    for q in q_keys:
        headers.extend([f"{q.upper()}_Moodle", f"{q.upper()}_IA", f"{q.upper()}_Tipo", f"{q.upper()}_Confianca"])
    headers.extend(["Total_Moodle", "Total_IA", "Diferenca", "Revisar_Manualmente"])

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for r in valid_results:
            row = [r["student"], r["login"]]
            tipos = r.get("tipos_detectados", {})
            confs = r.get("confiancas", {})
            precisa_revisar = False
            for q in q_keys:
                row.append(f"{r['moodle_parciais'].get(q, 0.0):.1f}")
                row.append(f"{r['ia_parciais'].get(q, 0.0):.1f}")
                row.append(tipos.get(q, "N/A"))
                conf_q = confs.get(q, "N/A")
                row.append(conf_q)
                if "baixa" in conf_q.lower() or "fallback" in conf_q.lower():
                    precisa_revisar = True
            row.extend([
                f"{r['moodle_total']:.1f}",
                f"{r['ia_total']:.1f}",
                f"{r['diff']:+.1f}",
                "SIM" if precisa_revisar else ""
            ])
            writer.writerow(row)
    logger.info(f"📊 Relatório CSV gerado com sucesso em: {output_path}")