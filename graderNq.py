"""
graderNq.py — Correção assíncrona de provas com N questões.

Detecta automaticamente o tipo de cada questão pelo código do aluno.
A LLM identifica o tipo da questão e avalia em uma única chamada.
O prompt universal (grading.prompt_file) contém as rubricas de todos os tipos.

Provider selecionado via config.yaml → llm.provider: groq | deepseek
Os modelos do provider ativo são variados em sequência até obter resposta.
"""

from __future__ import annotations
import argparse, asyncio, importlib, logging, re, sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# Importação dinâmica do cliente LLM conforme provider configurado
# =============================================================================

def load_llm_client(provider: str):
    """
    Retorna a classe LLMClientProva do módulo correspondente ao provider.
      groq      → llm_interface_prova_groq
      deepseek  → llm_interface_prova_deepseek
    """
    module_map = {
        "groq":     "llm_interface_prova_groq",
        "deepseek": "llm_interface_prova_deepseek",
    }
    module_name = module_map.get(provider)
    if not module_name:
        logger.error(f"❌ Provider desconhecido: '{provider}'. Use 'groq' ou 'deepseek'.")
        sys.exit(1)
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        logger.error(f"❌ Módulo '{module_name}.py' não encontrado no diretório.")
        sys.exit(1)
    if not hasattr(mod, "LLMClientProva"):
        logger.error(f"❌ '{module_name}.py' não define a classe LLMClientProva.")
        sys.exit(1)
    return mod.LLMClientProva


# =============================================================================
# Extração de nota (IA)
# =============================================================================

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


# =============================================================================
# Extração de nota (Moodle)
# =============================================================================

def extrair_nota_moodle(p: Optional[Path], grade_file: Optional[Path] = None) -> str:
    # Prioridade 1: grade.txt — contém apenas a nota final (ex: "79.16500")
    if grade_file and grade_file.exists():
        try:
            t = grade_file.read_text(errors='replace').strip()
            v = float(t.replace(',', '.'))
            if 0 <= v <= 100:
                return f"{v:.3f}"
        except Exception:
            pass
    # Prioridade 2: execution.txt — busca "Grade :=>> XX.XX" (nota final, não parcial)
    if not p or not p.exists(): return "0.00"
    try:
        t = p.read_text(errors='replace')
        m = re.search(r'^Grade\s*:=+>>\s*([0-9]+(?:[.,][0-9]+)?)', t, re.MULTILINE)
        if m: return m.group(1).replace(',', '.')
        m = re.search(r'\(([0-9]+(?:[.,][0-9]+)?)%\)', t)
        if m: return m.group(1).replace(',', '.')
    except Exception: pass
    return "0.00"

def extrair_parciais_moodle(p: Optional[Path], q_weights: dict) -> dict[int, float]:
    """
    Lê o execution.txt e extrai o PartialGrade de cada questão, na ordem
    em que aparecem (Q1, Q2, …).  Retorna {q: pct} onde pct está em 0‒100.
    """
    parciais: dict[int, float] = {}
    if not p or not p.exists():
        return parciais
    try:
        t = p.read_text(errors='replace')
        valores = re.findall(r'PartialGrade\s*:=+>>\s*([0-9]+(?:[.,][0-9]+)?)', t)
        for i, q in enumerate(sorted(q_weights)):
            if i < len(valores):
                parciais[q] = float(valores[i].replace(',', '.'))
    except Exception:
        pass
    return parciais


# =============================================================================
# Localização de arquivos
# =============================================================================

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
    ceg = sd / (sub.name + ".ceg")
    ef = ceg / "execution.txt"
    return ef if ef.exists() else None

def find_grade_file(sd: Path, sub: Path) -> Optional[Path]:
    ceg = sd / (sub.name + ".ceg")
    gf = ceg / "grade.txt"
    return gf if gf.exists() else None


# =============================================================================
# Formatação de rubrica
# =============================================================================

W = 76

def _t(): return "┌" + "─"*W + "┐"
def _b(): return "└" + "─"*W + "┘"
def _s(): return "├" + "─"*W + "┤"
def _r(s): return "│" + s + " "*max(0, W - len(s)) + "│"
def box(ls): return "\n".join([_t()] + [_r(l) for l in ls] + [_b()])

def _wrap(text: str, indent: str = "  ") -> list[str]:
    import textwrap, re as _re
    text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = text.replace('`', '')
    lines = []
    for paragraph in text.splitlines():
        if paragraph.strip() == "":
            lines.append(_r(""))
            continue
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


def build_rubrica(name, responses, code_files, tipos,
                  moodle_exec, grade_file, q_weights, provider):
    L = []
    total = sum(q_weights.values())
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L.append(box([
        f" ALUNO   : {name}",
        f" DATA    : {now}",
        f" PROVIDER: {provider.upper()}",
        f" QUESTÕES: {len(q_weights)}  " +
        "  ".join(f"Q{k}={v}pts" for k,v in sorted(q_weights.items())),
    ]))
    L.append("")

    nm = extrair_nota_moodle(moodle_exec, grade_file)   # <-- passa grade_file
    parciais_moodle = extrair_parciais_moodle(moodle_exec, q_weights)

    try:    nv = float(nm)
    except: nv = 0.0
    detalhes_vpl = "  ".join(
        f"Q{q}={parciais_moodle.get(q,0):.2f}%={parciais_moodle.get(q,0)*q_weights[q]/100:.3f}pts"
        for q in sorted(q_weights)
    )
    L += [_t(), _r(" CORREÇÃO MOODLE (VPL)"), _s(),
        _r(f"  Por questão : {detalhes_vpl}"),
        _r(f"  Nota total  : {nm}%  →  {nv*total/100:.2f} / {total} pts"), _b(), ""]

    ia: dict[int, float] = {}
    for q in sorted(q_weights):
        w  = q_weights[q]
        rp = responses.get(q)
        cf = code_files.get(q)
        tp = tipos.get(q, "?")

        L += [_t(), _r(f" Q{q}  (peso: {w} pts)  —  Tipo detectado: {tp}"), _s()]

        if cf and cf.exists():
            L += [_r(f" Arquivo: {cf.name}"), _s()]
            for ln in cf.read_text(errors='replace').splitlines():
                L.append("  " + ln)
            L.append(_s())
        else:
            L.append(_r(f" ⚠ Q{q}.* não encontrado na submissão"))

        L += [_r(f" AVALIAÇÃO DA IA — Q{q} (TIPO {tp})"), _s()]
        if rp and rp.success and rp.content:
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

    ti = sum(ia.values())
    mp = nv * total / 100
    sep = "  " + "─" * (W - 4)
    L += [_t(), _r("   RESUMO — MOODLE  x  IA"), _s(),
          _r(f"   Peso total : {total} pts"), _r(sep)]
    for q in sorted(q_weights):
        L.append(_r(f"   Q{q} (IA, TIPO {tipos.get(q,'?')}) : "
                    f"{ia.get(q,0):.0f} / {q_weights[q]} pts"))
        
    partes_moodle = " + ".join(
        f"Q{q}={parciais_moodle.get(q,0):.2f}%"
        f"={parciais_moodle.get(q,0)*q_weights[q]/100:.3f}"
        for q in sorted(q_weights)
    )

    L += [_r(sep),
          _r(f"   Moodle : ({partes_moodle}) = {nm}% → "),
          _r(f"            {mp:.0f} / {total} pts"),
          _r(f"   IA     : {ti:.0f} / {total} pts"),
          _r(sep),
          _r(f"   Diferença (IA - Moodle): {ti-mp:+.2f} pts"),
          _b(), ""]

    if moodle_exec and moodle_exec.exists():
        L += ["─" * (W + 2),
              " LOG BRUTO — CORREÇÃO DO MOODLE",
              "─" * (W + 2),
              moodle_exec.read_text(errors='replace').strip(),
              "─" * (W + 2), ""]

    L.append(box([f" ALUNO: {name}"]))
    return "\n".join(L)


# =============================================================================
# Processamento de um aluno
# =============================================================================

async def process_student(sd, llm, q_weights, universal_prompt,
                          min_lines, min_chars, exts, sem, rubric_fname, provider):
    name = sd.name
    logger.info(f"→ {name}")
    subdir = find_submission_dir(sd)
    if not subdir:
        logger.warning("  ⚠ Sem submissão — pulando")
        return {"student": name, "status": "skipped", "reason": "sem submissão"}

    rpath = subdir / rubric_fname
    if rpath.exists():
        logger.info(f"  ⏭ Rubrica já existe — lendo arquivo local")
        try:
            conteudo_existente = rpath.read_text(encoding='utf-8')
            return {"student": name, "status": "ok", "content": conteudo_existente, "from_cache": True}
        except Exception as e:
            logger.error(f"  ❌ Erro ao ler rubrica existente: {e}")
            return {"student": name, "status": "failed", "reason": "erro leitura local"}

    moodle_exec = find_moodle_exec(sd, subdir)
    grade_file   = find_grade_file(sd, subdir)
    code_files  = {q: find_code_file(subdir, q, exts) for q in q_weights}

    # Importa LLMResponse do módulo correto para criar respostas de erro inline
    mod_name = "llm_interface_prova_deepseek" if provider == "deepseek" else "llm_interface_prova_groq"
    LLMResponse = importlib.import_module(mod_name).LLMResponse

    async def call_one(q):
        w  = q_weights[q]
        cf = code_files.get(q)
        if cf is None:
            return q, LLMResponse(success=False, content="", model_used="",
                                  duration_seconds=0.0,
                                  error=f"Q{q}.* não encontrado")
        code_text = cf.read_text(errors='replace')
        if len(code_text.splitlines()) < min_lines:
            return q, LLMResponse(success=False, content="", model_used="",
                                  duration_seconds=0.0,
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

    tipos: dict[int, str] = {}
    for q, resp in responses.items():
        if resp.success and resp.content:
            m = re.search(r'Tipo identificado\s*:\s*([A-Z]+)', resp.content, re.IGNORECASE)
            tipos[q] = m.group(1).upper() if m else "?"
        else:
            tipos[q] = "?"

    # build_rubrica precisa receber grade_file também
    rubrica = build_rubrica(name, responses, code_files, tipos,
                            moodle_exec, grade_file, q_weights, provider)

    rpath   = subdir / rubric_fname
    rpath.write_text(rubrica, encoding='utf-8')
    logger.info(f"  💾 {rpath.relative_to(sd.parent)}")
    return {"student": name, "status": "ok", "content": rubrica}


# =============================================================================
# Main
# =============================================================================

async def main_async(args):
    cfg   = yaml.safe_load(open(args.config, encoding='utf-8'))
    grade = cfg.get('grading', {})
    paths = cfg.get('paths', {})

    # ── Provider ──────────────────────────────────────────────────────────────
    provider = cfg.get('llm', {}).get('provider', 'groq').strip().lower()
    if provider not in ('groq', 'deepseek'):
        logger.error(f"❌ llm.provider inválido: '{provider}'. Use 'groq' ou 'deepseek'.")
        sys.exit(1)

    # Seção de config do provider ativo
    provider_cfg = cfg.get(provider, {})
    api_key = provider_cfg.get('api_key', '')
    if not api_key or 'COLOQUE' in api_key:
        logger.error(f"❌ {provider}.api_key não configurada em config.yaml")
        sys.exit(1)

    # Normaliza models para lista
    raw_models = provider_cfg.get('models', [])
    models = [raw_models] if isinstance(raw_models, str) else list(raw_models)
    if not models:
        logger.error(f"❌ {provider}.models não configurado em config.yaml")
        sys.exit(1)

    if not grade.get('use_llm', True):
        logger.warning("⚠ use_llm: false — análise da IA desativada.")
        sys.exit(0)

    # ── Pasta de alunos ───────────────────────────────────────────────────────
    student_base_str = args.student_dir or paths.get('student_base_dir', '')
    if not student_base_str:
        logger.error("❌ Informe a pasta de alunos ou configure paths.student_base_dir")
        sys.exit(1)
    base = Path(student_base_str)
    if not base.is_dir():
        logger.error(f"❌ Pasta não encontrada: {base}")
        sys.exit(1)

    # ── Parâmetros de avaliação ───────────────────────────────────────────────
    q_weights = {int(re.sub(r'\D', '', str(k))): int(v)
                 for k, v in grade.get('weights', {}).items()}
    if not q_weights:
        logger.error("❌ grading.weights não configurado")
        sys.exit(1)

    min_lines   = int(grade.get('min_code_lines', 4))
    min_chars   = int(provider_cfg.get('min_response_chars', 5))
    rubric_name = paths.get('output_rubric_filename', 'rubrica.txt')
    exts        = grade.get('supported_extensions', DEFAULT_EXTS)

    # ── Prompt universal — lido de grading.prompt_file ────────────────────────
    prompt_file = Path(grade.get('prompt_file', 'prompt.txt'))
    if not prompt_file.exists():
        logger.error(f"❌ Prompt não encontrado: {prompt_file}")
        logger.error(f"   Verifique grading.prompt_file em {args.config}")
        sys.exit(1)
    universal_prompt = prompt_file.read_text(encoding='utf-8')

    # ── Pastas de alunos ──────────────────────────────────────────────────────
    student_dirs = sorted([d for d in base.iterdir()
                           if d.is_dir() and not d.name.startswith('.')])
    if not student_dirs:
        logger.error(f"❌ Nenhuma pasta de aluno em '{base}'")
        sys.exit(1)

    logger.info(f"\n  Provider     : {provider.upper()}")
    logger.info(f"  Prompt       : {prompt_file}")
    logger.info(f"  Pasta        : {base}")
    logger.info(f"  Alunos       : {len(student_dirs)}")
    logger.info(f"  Questões     : {', '.join(f'Q{k}={v}pts' for k,v in sorted(q_weights.items()))}")
    logger.info(f"  Extensões    : {exts}")
    logger.info(f"  Modelos      : {models}")
    logger.info(f"  Concorrência : {args.max_concurrent}\n")

    # ── Carrega cliente LLM conforme provider ─────────────────────────────────
    LLMClientProva = load_llm_client(provider)

    sem = asyncio.Semaphore(args.max_concurrent)
    async with LLMClientProva(config=cfg) as llm:
        results = await asyncio.gather(*[
            process_student(d, llm, q_weights, universal_prompt,
                            min_lines, min_chars, exts, sem, rubric_name, provider)
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