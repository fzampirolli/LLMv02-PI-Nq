import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from .utils import extrair_nota_ia, find_latest_submission, get_code_content, extrair_dados_vpl

logger = logging.getLogger(__name__)
import re
import textwrap

W = 96

def _t(): return "┌" + "─" * W + "┐"
def _b(): return "└" + "─" * W + "┘"
def _s(): return "├" + "─" * W + "┤"

def _r(s):
    s = str(s).replace('\n', ' ').strip()
    return "│ " + s.ljust(W - 2)[:W-2] + " │"


def formatar_texto_IA(texto, W=80):
    def quebra_linha(linha, W):
        # Detecta indentação (espaços iniciais)
        indent = len(linha) - len(linha.lstrip())
        prefixo = linha[:indent]
        conteudo = linha.strip()

        # Detecta bullet (-, *, etc.)
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
    for linha in texto.split("\n"):
        if linha.strip() == "":
            resultado.append("")  # mantém linha em branco
        else:
            resultado.extend(quebra_linha(linha, W))

    return "\n".join(resultado)

async def process_student(student_path: Path, client, config: Dict, semaphore: asyncio.Semaphore):
    async with semaphore:
        student_name = student_path.name
        # Extrai o login do nome da pasta (Ex: "Nome - login")
        login = student_name.split(" - ")[-1] if " - " in student_name else student_name
        
        sub_dir = find_latest_submission(student_path)
        if not sub_dir: 
            return None

        rubric_name = config['paths'].get('output_rubric_filename', 'rubrica.txt')
        rubric_path = sub_dir / rubric_name
        weights = config['grading']['weights']
        total_peso = sum(weights.values())

        # --- INICIALIZAÇÃO DE VARIÁVEIS DE RETORNO ---
        full_content = ""
        moodle_data = extrair_dados_vpl(sub_dir, weights)
        ia_parciais = {k: 0.0 for k in weights.keys()}
        ia_total = 0.0

        # --- LÓGICA DE CACHE ---
        if rubric_path.exists():
            try:
                full_content = rubric_path.read_text(encoding='utf-8')
                
                # Tenta recuperar as notas da IA do arquivo existente para o CSV
                for q_key in weights.keys():
                    # Procura por "Q1 (IA) : 45.0"
                    padrao = rf"{q_key.upper()}\s*\(IA\)\s*:\s*([\d.]+)"
                    match = re.search(padrao, full_content, re.IGNORECASE)
                    if match:
                        ia_parciais[q_key] = float(match.group(1))
                
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
                    "diff": ia_total - moodle_data['total']
                }
            except Exception as e:
                logger.warning(f"  ⚠️ Erro ao ler cache de {student_name}, reavaliando: {e}")

        # --- NOVA CONSULTA (API) ---
        logger.info(f"  🤖 {student_name}: Consultando API...")
        ia_blocks = []
        prompt_path = Path(config['grading']['prompt_file'])
        system_prompt = prompt_path.read_text(encoding='utf-8')
        extensions = config['grading'].get('supported_extensions', ['py', 'java', 'cpp'])

        # --- Dentro da função process_student, no loop das questões ---
        for q_key, weight in weights.items():
            q_num = int(''.join(filter(str.isdigit, q_key)))
            code = get_code_content(sub_dir, q_num, extensions)
            
            if not code:
                ia_parciais[q_key] = 0.0
                continue

            # Chamada da API
            response = await client.chat_completion(system_prompt, code)

            # Extração de nota de forma segura
            nota_extraida = extrair_nota_ia(response.content, weight) if response.success else "0"
            try:
                # Se extrair_nota_ia retornar "?", define como 0.0 para não quebrar o float()
                nota = float(nota_extraida) if nota_extraida != "?" else 0.0
            except ValueError:
                nota = 0.0

            ia_parciais[q_key] = nota
            ia_total += nota

            if response.success:
                # 1. Identifica o Tipo selecionado pela IA
                match_tipo = re.search(r'Tipo identificado\s*:\s*([A-Z])', response.content, re.IGNORECASE)
                tipo_detectado = match_tipo.group(1).upper() if match_tipo else "?" 

                # 2. Carrega o conteúdo do promptP3.txt
                prompt_content = Path(config['grading']['prompt_file']).read_text(encoding='utf-8')

                # 3. Regex simplificada usando as novas tags [START_RUBRICA_X] e [END_RUBRICA_X]
                # O padrão .*? com re.DOTALL captura tudo entre as tags, incluindo quebras de linha.
                regex_rubrica = rf"\[START_RUBRICA_{tipo_detectado}\](.*?)\[END_RUBRICA_{tipo_detectado}\]"
                match_rubrica = re.search(regex_rubrica, prompt_content, re.DOTALL)

                if match_rubrica:
                    rubrica_texto = match_rubrica.group(1).strip()
                else:
                    rubrica_texto = f"ERRO: Critérios para TIPO {tipo_detectado} não encontrados no prompt."
                

                # 4. Limpeza do corpo da resposta (evita duplicar o "Tipo identificado")
                clean_content = re.sub(r'(?i)Tipo identificado\s*:\s*[A-Z]', '', response.content).strip()

                # --- MONTAGEM DO BLOCO ---
                ia_blocks.append(_t())
                ia_blocks.append(_r(f"Q{q_num} - CÓDIGO DO ALUNO"))
                ia_blocks.append(_s())
                ia_blocks.append("")
                ia_blocks.append(code)
                ia_blocks.append("")

                # ── 1. Cabeçalho da rubrica ───────────────────────────────────────────
                ia_blocks.append(_s())
                ia_blocks.append(_r(f"CRITÉRIOS DE CORREÇÃO (TIPO {tipo_detectado})"))  # ← era "REGRA DE AVALIAÇÃO APLICADA"
                ia_blocks.append(_s())
                #ia_blocks.append(rubrica_texto)
                
                # Adiciona separador abaixo do título da rubrica antes de exibi-la
                linhas_rubrica = rubrica_texto.splitlines()
                if linhas_rubrica:
                    ia_blocks.append("")
                    ia_blocks.append(linhas_rubrica[0])                        # "RUBRICA DO TIPO A — ..."
                    ia_blocks.append("-" * len(linhas_rubrica[0]))             # "─────────────────────"  ← novo
                    ia_blocks.extend(linhas_rubrica[1:])                       # resto da rubrica
                    ia_blocks.append("")

                # ── 2. Cabeçalho da avaliação IA ──────────────────────────────────────
                ia_blocks.append(_s())
                ia_blocks.append(_r(f"AVALIAÇÃO TIPO {tipo_detectado} - Q{q_num} (Peso {weight} pts)"))  # ← era "AVALIAÇÃO IA (deepseek-chat)"
                ia_blocks.append(_s())

                ia_blocks.append("")
                ia_blocks.append(formatar_texto_IA(clean_content, W))
                ia_blocks.append("")
                
                ia_blocks.append(_b())
                ia_blocks.append("")

        # --- MONTAGEM DA TABELA (QUADRO VISUAL) ---
        diff = ia_total - moodle_data['total']
        m_parts = " + ".join([f"{k.upper()}={v:.0f}" for k, v in moodle_data['parciais'].items()])
                
        # --- MONTAGEM DA TABELA DE RESUMO ---
        # Pega o nome do modelo da última resposta válida ou do config
        modelo_nome = response.model_used if 'response' in locals() and hasattr(response, 'model_used') else config.get('llm', {}).get('provider', 'IA').upper()

        resumo = []
        resumo.append(_t())
        resumo.append(_r(f"RESUMO — IA ({modelo_nome})  x  MOODLE")) # Incluído aqui
        resumo.append(_s())
        resumo.append(_r(f"Peso total : {total_peso} pts"))
        resumo.append(_r("─" * (W-2)))

        for q_key, w in weights.items():
            nota_ia = ia_parciais.get(q_key, 0.0)
            resumo.append(_r(f"{q_key.upper()} (IA) : {nota_ia:>4.0f} / {w} pts"))

        resumo.append(_r("─" * (W-2)))
        m_parts = " + ".join([f"{k.upper()}={v:.0f}" for k, v in moodle_data['parciais'].items()])
        resumo.append(_r(f"Moodle : ({m_parts}) = {moodle_data['total']:.0f} pts"))
        resumo.append(_r(f"IA     : {ia_total:.0f} / {total_peso} pts"))
        resumo.append(_r("─" * (W-2)))
        resumo.append(_r(f"Diferença (IA - Moodle): {ia_total - moodle_data['total']:>+5.0f} pts"))
        resumo.append(_b())

        full_content = "\n".join(resumo) + "\n" + "\n".join(ia_blocks)
        rubric_path.write_text(full_content, encoding='utf-8')

        return {
            "status": "ok",
            "student": student_name,
            "login": login,
            "content": full_content,
            "moodle_parciais": moodle_data['parciais'],
            "ia_parciais": ia_parciais,
            "moodle_total": moodle_data['total'],
            "ia_total": ia_total,
            "diff": diff
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