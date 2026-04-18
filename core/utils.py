import re
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# =============================================================================
# EXTRAÇÃO DE NOTAS (IA)
# =============================================================================

def extrair_nota_ia(texto: str, peso_max: int) -> str:
    """
    Analisa o retorno da LLM em busca da nota final baseada em padrões comuns.
    Adaptado para ser flexível com diferentes formatos de resposta.
    """
    # Padrão 1: Soma explícita (ex: 10 + 20 + 5 = 35)
    m = re.search(r'[0-9]+(?:[^+\n=]*\+[^+\n=]*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)', texto)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 <= v <= peso_max: return m.group(1).replace(',', '.')

    # Padrão 2: Formato TOTAL/PESO (ex: 45/50)
    #m = re.search(r'([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(peso_max), texto)
    m = re.search(r'\[?([0-9]+(?:[.,][0-9]+)?)\]?\s*/\s*' + str(peso_max), texto)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 <= v <= peso_max: return m.group(1).replace(',', '.')

    # Padrão 3: Palavras-chave (ex: Nota Final: 40 pontos)
    #m = re.search(r'(?:nota\s*final|total|pontuação)[^:\n]*[:\→]\s*([0-9]+(?:[.,][0-9]+)?)', texto, re.IGNORECASE)
    m = re.search(r'(?:nota\s*final|total|pontuação)[^:\n]*[:\→]\s*\[?([0-9]+(?:[.,][0-9]+)?)\]?', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if 0 <= v <= peso_max: return m.group(1).replace(',', '.')

    # Fallback: Busca o último número isolado que faça sentido no intervalo
    numeros = re.findall(r'\b([0-9]+(?:[.,][0-9]+)?)\b', texto)
    for n in reversed(numeros):
        try:
            v = float(n.replace(',', '.'))
            if 0 <= v <= peso_max: return n.replace(',', '.')
        except ValueError: continue

    return "?"


# =============================================================================
# LOCALIZAÇÃO DE ARQUIVOS
# =============================================================================

def find_latest_submission(student_dir: Path) -> Optional[Path]:
    """
    Localiza a pasta de submissão mais recente (YYYY-MM-DD-...).
    Ignora pastas .ceg e foca nas pastas de código.
    """
    sub_dirs = sorted(
        [d for d in student_dir.iterdir() 
         if d.is_dir() and re.match(r'\d{4}', d.name) and not d.name.endswith('.ceg')],
        reverse=True
    )
    return sub_dirs[0] if sub_dirs else None

def get_code_content(sub_dir: Path, q_num: int, extensions: list) -> Optional[str]:
    # Tenta pelo padrão Qi.* (prova com múltiplas questões)
    for ext in extensions:
        f = sub_dir / f"Q{q_num}.{ext}"
        if f.exists():
            return f.read_text(errors='replace')
    
    # Fallback: prova com única questão — pega qualquer arquivo com extensão suportada
    arquivos = [
        f for f in sub_dir.iterdir()
        if f.is_file() and f.suffix.lstrip('.') in extensions
    ]
    
    # Só usa o fallback se houver exatamente 1 arquivo (garante que é prova de 1 questão)
    if len(arquivos) == 1:
        return arquivos[0].read_text(errors='replace')
    
    return None



def extrair_dados_vpl(sub_dir: Path, weights: Dict[str, int]) -> Dict:
    """
    Extrai notas do Moodle a partir do execution.txt e converte para pontos.
    """
    dados = {"total": 0.0, "parciais": {k: 0.0 for k in weights.keys()}}
    
    # A pasta .ceg contém o execution.txt com os resultados do VPL
    ceg_dir = sub_dir.parent / f"{sub_dir.name}.ceg"
    exec_file = ceg_dir / "execution.txt"

    if exec_file.exists():
        content = exec_file.read_text(errors='replace')
        
        # Procura por 'PartialGrade :=>> 100' ou similar
        # O regex captura o número após o símbolo de atribuição do VPL
        parciais_vpl = re.findall(r'PartialGrade\s*:=+>>\s*([\d.]+)', content)
        
        # Atribui as notas na ordem em que aparecem (Q1, Q2...)
        for i, (q_key, weight) in enumerate(weights.items()):
            if i < len(parciais_vpl):
                percentual = float(parciais_vpl[i])
                # Converte o percentual (0-100) para a escala de pontos (ex: peso 50)
                pontos = (percentual / 100.0) * weight
                dados["parciais"][q_key] = pontos
        
        dados["total"] = sum(dados["parciais"].values())
    
    return dados