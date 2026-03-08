"""
graderNq.py — Correção assíncrona de provas com N questões.
Detecta automaticamente o tipo de cada questão pelo código do aluno.
  A LLM identifica o tipo da questão e avalia em uma única chamada.
  O prompt universal (prompt.txt) contém as rubricas de todos os tipos.
"""

from __future__ import annotations
import argparse, asyncio, logging, re, sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml
from llm_interface_prova import LLMClientProva, LLMResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Extração de nota (IA) ─────────────────────────────────────────────────────

def extrair_nota_texto(texto: str, q_weight: int) -> str:
    m = re.search(r'[0-9]+(?:[^+\n=]*\+[^+\n=]*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 < v <= q_weight: return m.group(1).replace(',', '.')
    m = re.search(r'[0-9]+(?:\s*\+\s*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 < v <= q_weight: return m.group(1).replace(',', '.')
    m = re.search(r'=\s*([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(q_weight), texto, re.IGNORECASE)
    if m: return m.group(1).replace(',', '.')
    m = re.search(r'([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(q_weight), texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 <= v <= q_weight: return m.group(1).replace(',', '.')
    m = re.search(r'(?:nota\s*final|total)[^:\n]*[:\→]\s*([0-9]+(?:[.,][0-9]+)?)\s*pontos', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 < v <= q_weight: return m.group(1).replace(',', '.')
    m = re.search(r'[→>]\s*([0-9]+(?:[.,][0-9]+)?)\s*pontos', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 < v <= q_weight: return m.group(1).replace(',', '.')
    for n in reversed(re.findall(r'\b([0-9]+(?:[.,][0-9]+)?)\b', texto)):
        try:
            v = float(n.replace(',', '.'))
            if 0 < v <= q_weight: return n.replace(',', '.')
        except ValueError: continue
    return "?"

# ── Extração de nota (Moodle) ─────────────────────────────────────────────────

def extrair_nota_moodle(p: Optional[Path]) -> str:
    if not p or not p.exists(): return "N/A"
    try:
        t = p.read_text(errors='replace')
        m = re.search(r'Grade\s*:=+>>\s*([0-9]+(?:[.,][0-9]+)?)', t)
        if m: return m.group(1).replace(',', '.')
        m = re.search(r'\(([0-9]+(?:[.,][0-9]+)?)%\)', t)
        if m: return m.group(1).replace(',', '.')
    except Exception: pass
    return "0.00"

# ── Localização de arquivos ───────────────────────────────────────────────────

DEFAULT_EXTS = ['py', 'java', 'c', 'cpp', 'js', 'ts', 'r', 'R']

def find_submission_dir(d: Path) -> Optional[Path]:
    c = sorted([x for x in d.iterdir()
                if x.is_dir() and not x.name.endswith('.ceg')
                and re.match(r'\d{4}-\d{2}-\d{2}', x.name)],
               key=lambda x: x.name, reverse=True)
    return c[0] if c else None

def find_code_file(d: Path, q: int, exts: list[str]) -> Optional[Path]:
    for ext in exts:
        f = d / f"Q{q}.{ext}"
        if f.exists(): return f
    return None

def find_moodle_exec(sd: Path, sub: Path) -> Optional[Path]:
    ef = sd / (sub.name + ".ceg") / "execution.txt"
    return ef if ef.exists() else None

# ── Formatação ────────────────────────────────────────────────────────────────

W = 76   # largura interna (entre │ e │)

def _t(): return "┌" + "─"*W + "┐"
def _b(): return "└" + "─"*W + "┘"
def _s(): return "├" + "─"*W + "┤"
def _r(s): return "│" + s + " "*max(0, W - len(s)) + "│"
def box(ls): return "\n".join([_t()] + [_r(l) for l in ls] + [_b()])

def _wrap(text: str, indent: str = "  ") -> list[str]:
    """
    Quebra uma string longa em múltiplas linhas que cabem dentro da caixa.
    Preserva linhas em branco e respeita recuo do texto original.
    Remove negrito markdown (**texto**).
    """
    import textwrap, re as _re
    # Remove negrito markdown
    text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # Remove backticks inline
    text = text.replace('`', '')

    max_w = W - len(indent) - 1   # espaço disponível dentro da borda
    lines = []
    for paragraph in text.splitlines():
        if paragraph.strip() == "":
            lines.append(_r(""))
            continue
        # Preserva indentação original do parágrafo
        stripped = paragraph.lstrip()
        orig_indent = paragraph[: len(paragraph) - len(stripped)]
        prefix = indent + orig_indent
        available = W - len(prefix) - 1
        if available < 10:
            available = W - len(indent) - 1
            prefix = indent
        for chunk in textwrap.wrap(stripped, width=available) or [stripped]:
            lines.append(_r(prefix + chunk))
    return lines

# ── Rubrica ───────────────────────────────────────────────────────────────────

def build_rubrica(name, responses, code_files, tipos, moodle_exec, q_weights):
    L = []
    total = sum(q_weights.values())
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L.append(box([
        f" ALUNO   : {name}",
        f" DATA    : {now}",
        f" QUESTÕES: {len(q_weights)}  " +
        "  ".join(f"Q{k}={v}pts" for k,v in sorted(q_weights.items())),
    ]))
    L.append("")

    nm = extrair_nota_moodle(moodle_exec)
    try:    nv = float(nm)
    except: nv = 0.0
    L += [_t(), _r(" CORREÇÃO MOODLE (VPL)"), _s(),
          _r(f"  Nota : {nm}%  →  {nv*total/100:.2f} / {total} pts"), _b(), ""]

    ia: dict[int, float] = {}
    for q in sorted(q_weights):
        w  = q_weights[q]
        rp = responses.get(q)
        cf = code_files.get(q)
        tp = tipos.get(q, "?")

        L += [_t(), _r(f" Q{q}  (peso: {w} pts)  —  Tipo detectado: {tp}"), _s()]

        # Código submetido — sem bordas laterais, texto livre
        if cf and cf.exists():
            L += [_r(f" Arquivo: {cf.name}"), _s()]
            for ln in cf.read_text(errors='replace').splitlines():
                L.append("  " + ln)        # sem │ nas bordas
            L.append(_s())                  # fecha bloco de código com ├───┤
        else:
            L.append(_r(f" ⚠ Q{q}.* não encontrado na submissão"))

        # Avaliação IA
        L += [_r(f" AVALIAÇÃO DA IA — Q{q} (TIPO {tp})"), _s()]
        if rp and rp.success and rp.content:
            # Aplica word-wrap em cada linha da resposta da IA
            for ln in rp.content.splitlines():
                L.extend(_wrap(ln, indent="  "))
            ns = extrair_nota_texto(rp.content, w)
            try:    ia[q] = float(ns)
            except: ia[q] = 0.0
            L += [_s(),
                  _r(f"  Nota IA : {ns} / {w} pts"),
                  _r(f"  Modelo  : {rp.model_used}"),
                  _r(f"  Tempo   : {rp.duration_seconds:.1f}s")]
        else:
            err = rp.error if rp else "sem resposta"
            L.append(_r(f" ❌ Falha: {err}"))
            ia[q] = 0.0

        L += [_b(), ""]

    # Resumo comparativo
    ti = sum(ia.values())
    mp = nv * total / 100
    sep = "  " + "─" * (W - 4)
    L += [_t(), _r("   RESUMO — MOODLE  x  IA"), _s(),
          _r(f"   Peso total : {total} pts"), _r(sep)]
    for q in sorted(q_weights):
        L.append(_r(f"   Q{q} (IA, TIPO {tipos.get(q,'?')}) : "
                    f"{ia.get(q,0):.0f} / {q_weights[q]} pts"))
    L += [_r(sep),
          _r(f"   Moodle : {nm}%  →  {mp:.2f} / {total} pts"),
          _r(f"   IA     : {ti:.0f} / {total} pts"),
          _r(sep),
          _r(f"   Diferença (IA - Moodle): {ti-mp:+.2f} pts"),
          _b(), ""]

    # Log bruto Moodle — sem caixa, texto livre
    if moodle_exec and moodle_exec.exists():
        L += ["─" * (W + 2),
              " LOG BRUTO — CORREÇÃO DO MOODLE",
              "─" * (W + 2),
              moodle_exec.read_text(errors='replace').strip(),
              "─" * (W + 2), ""]

    L.append(box([f" ALUNO: {name}"]))
    return "\n".join(L)

# ── Processamento de um aluno ─────────────────────────────────────────────────

async def process_student(sd, llm, q_weights, universal_prompt,
                           min_lines, min_chars, exts, sem, rubric_fname):
    name = sd.name
    logger.info(f"→ {name}")
    subdir = find_submission_dir(sd)
    if not subdir:
        logger.warning("  ⚠ Sem submissão — pulando")
        return {"student": name, "status": "skipped", "reason": "sem submissão"}

    # === NOVA LÓGICA: Se existir, lê e retorna para o consolidado ===
    rpath = subdir / rubric_fname
    if rpath.exists():
        logger.info(f"  ⏭ Rubrica já existe — lendo arquivo local")
        try:
            conteudo_existente = rpath.read_text(encoding='utf-8')
            return {"student": name, "status": "ok", "content": conteudo_existente, "from_cache": True}
        except Exception as e:
            logger.error(f"  ❌ Erro ao ler rubrica existente: {e}")
            return {"student": name, "status": "failed", "reason": "erro leitura local"}
    # ===============================================================

    moodle_exec = find_moodle_exec(sd, subdir)
    code_files  = {q: find_code_file(subdir, q, exts) for q in q_weights}

    async def call_one(q):
        w  = q_weights[q]
        cf = code_files.get(q)
        if cf is None:
            return q, LLMResponse(success=False, content="", model_used="",
                                  attempts=0, duration_seconds=0.0,
                                  error=f"Q{q}.* não encontrado")
        code_text = cf.read_text(errors='replace')
        if len(code_text.splitlines()) < min_lines:
            return q, LLMResponse(success=False, content="", model_used="",
                                  attempts=0, duration_seconds=0.0,
                                  error=f"Código curto ({len(code_text.splitlines())} linhas, mínimo {min_lines})")
        prompt = (universal_prompt
                  + f"\n\nPeso máximo desta questão: {w} pontos.\n"
                  + f"Use o formato: Nota: X + Y + Z = TOTAL/{w}\n")
        ext = cf.suffix.lstrip('.')
        sep = "//" if ext in ('py','java','c','cpp','js','r') else "#"
        code_content = f"{sep} ===== Q{q} — {cf.name} =====\n{code_text}"
        async with sem:
            resp = await llm.call_grader(system_prompt=prompt, code_content=code_content)
        logger.info(f"  {'✓' if resp.success else '✗'} Q{q} — "
                    f"{resp.model_used or 'falhou'} ({resp.duration_seconds:.1f}s)")
        return q, resp

    results   = await asyncio.gather(*[call_one(q) for q in q_weights])
    responses = dict(results)

    if not any(r.success and r.content for r in responses.values()):
        logger.warning("  ⚠ Nenhuma resposta LLM válida")
        return {"student": name, "status": "failed", "reason": "sem resposta LLM"}

    # Extrai tipo identificado pela LLM para exibição na rubrica
    tipos: dict[int, str] = {}
    for q, resp in responses.items():
        if resp.success and resp.content:
            m = re.search(r'Tipo identificado\s*:\s*([A-Z]+)', resp.content, re.IGNORECASE)
            tipos[q] = m.group(1).upper() if m else "?"
        else:
            tipos[q] = "?"

    rubrica = build_rubrica(name, responses, code_files, tipos, moodle_exec, q_weights)
    rpath   = subdir / rubric_fname
    rpath.write_text(rubrica, encoding='utf-8')
    logger.info(f"  💾 {rpath.relative_to(sd.parent)}")
    return {"student": name, "status": "ok", "content": rubrica}

# ── Main ──────────────────────────────────────────────────────────────────────

async def main_async(args):
    cfg   = yaml.safe_load(open(args.config, encoding='utf-8'))
    groq  = cfg.get('groq', {})
    grade = cfg.get('grading', {})
    paths = cfg.get('paths', {})

    # ── Validações básicas ────────────────────────────────────────────────────
    api_key = groq.get('api_key', '')
    if not api_key or 'COLOQUE' in api_key:
        logger.error("❌ groq.api_key não configurada em config.yaml"); sys.exit(1)

    if not grade.get('use_llm', True):
        logger.warning("⚠ use_llm: false — análise da IA desativada."); sys.exit(0)

    # ── Pasta de alunos: argumento CLI > paths.student_base_dir ──────────────
    student_base_str = args.student_dir or paths.get('student_base_dir', '')
    if not student_base_str:
        logger.error("❌ Informe a pasta de alunos ou configure paths.student_base_dir"); sys.exit(1)
    base = Path(student_base_str)
    if not base.is_dir():
        logger.error(f"❌ Pasta não encontrada: {base}"); sys.exit(1)

    # ── Parâmetros de avaliação ───────────────────────────────────────────────
    q_weights = {int(re.sub(r'\D', '', str(k))): int(v)
                 for k, v in grade.get('weights', {}).items()}
    if not q_weights:
        logger.error("❌ grading.weights não configurado"); sys.exit(1)

    min_lines   = int(grade.get('min_code_lines', 4))
    min_chars   = int(groq.get('min_response_chars', 5))
    rubric_name = paths.get('output_rubric_filename', 'rubrica.txt')
    exts        = grade.get('supported_extensions', DEFAULT_EXTS)

    # ── Prompt universal ────────────────────────────────────────────────────
    prompt_file = Path(grade.get('prompt_file', 'prompt.txt'))
    if not prompt_file.exists():
        logger.error(f"❌ Prompt não encontrado: {prompt_file}"); sys.exit(1)
    universal_prompt = prompt_file.read_text(encoding='utf-8')
    logger.info(f"  📝 Prompt: {prompt_file}")

    # ── Pastas de alunos ──────────────────────────────────────────────────────
    student_dirs = sorted([d for d in base.iterdir()
                           if d.is_dir() and not d.name.startswith('.')])
    if not student_dirs:
        logger.error(f"❌ Nenhuma pasta de aluno em '{base}'"); sys.exit(1)

    logger.info(f"\n  Pasta        : {base}")
    logger.info(f"  Alunos       : {len(student_dirs)}")
    logger.info(f"  Questões     : {', '.join(f'Q{k}={v}pts' for k,v in sorted(q_weights.items()))}")
    logger.info(f"  Extensões    : {exts}")
    logger.info(f"  Modelos      : {groq.get('models', [])}")
    logger.info(f"  Concorrência : {args.max_concurrent}\n")

    # ── Execução ──────────────────────────────────────────────────────────────
    # LLMClientProva recebe o config completo (lê api_url, api_key, models, etc.)
    sem = asyncio.Semaphore(args.max_concurrent)
    async with LLMClientProva(config=cfg) as llm:
        results = await asyncio.gather(*[
            process_student(d, llm, q_weights, universal_prompt,
                            min_lines, min_chars, exts, sem, rubric_name)
            for d in student_dirs])

    # ── Consolida ALL.txt ─────────────────────────────────────────────────────
    all_path = base.parent / f"{base.name}_ALL.txt"
    ok = [r for r in results if r.get("status") == "ok"]
    with open(all_path, 'w', encoding='utf-8') as f:
        for r in ok:
            f.write(r.get("content", "") + "\n" + "═" * 60 + "\n\n")

    skipped = sum(1 for r in results if r.get("status") == "skipped")
    failed  = sum(1 for r in results if r.get("status") == "failed")
    logger.info(f"\n{'─'*58}")
    logger.info(f"  ✅ Processados : {len(ok)}")
    logger.info(f"  ⏭ Pulados     : {skipped}")
    logger.info(f"  ❌ Falhas      : {failed}")
    logger.info(f"  📄 Consolidado : {all_path}")
    logger.info(f"{'─'*58}\n")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("student_dir", nargs="?", default=None,
                   help="Pasta com submissões (ou use paths.student_base_dir no config.yaml)")
    p.add_argument("config", nargs="?", default="config.yaml")
    p.add_argument("--max-concurrent", type=int, default=3, dest="max_concurrent")
    asyncio.run(main_async(p.parse_args()))

if __name__ == "__main__":
    main()