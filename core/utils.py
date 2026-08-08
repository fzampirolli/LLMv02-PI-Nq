# utils.py

import re
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# =============================================================================
# EXTRAÇÃO DE NOTAS (IA)
# =============================================================================

def extrair_nota_ia(texto: str, peso_max) -> str:
    """
    Analisa o retorno da LLM em busca da nota final baseada em padrões comuns.

    IMPORTANTE: peso_max costuma vir do config.yaml como inteiro (ex.: 33),
    mas a rubrica do prompt pode calcular o máximo real como fração (ex.:
    33.33, resultado de 100/3). Isso faz a IA responder algo como
    "NOTA FINAL: 33.34/33.33", que é o valor MÁXIMO correto — mas que
    ultrapassa levemente o inteiro 33 do config. Por isso a validação usa
    uma tolerância de arredondamento em vez de um limite rígido; sem isso,
    respostas corretas eram descartadas e a extração caía num fallback que
    pega qualquer número solto do texto (ex.: "os 10 testes passaram"),
    gerando notas artificialmente baixas sem relação com a avaliação real.
    """
    peso_max = float(peso_max)
    tolerancia = max(peso_max * 0.03, 1.0)  # 3% do peso, ou 1 pt — o que for maior

    def valido(v: float) -> bool:
        return -1e-6 <= v <= peso_max + tolerancia

    def normaliza(v: float) -> str:
        # Trava no teto configurado, mesmo que a IA tenha calculado
        # um valor levemente acima por arredondamento da rubrica.
        return f"{min(v, peso_max):.2f}"

    # Padrão 0 (PRIORIDADE MÁXIMA): "NOTA FINAL: X/Y" explícito.
    # É o formato que o prompt EXIGE que a IA use — deve ser a primeira
    # fonte de verdade, antes de qualquer heurística genérica.
    m = re.search(
        r'NOTA\s+FINAL\s*:?\s*\[?([0-9]+(?:[.,][0-9]+)?)\]?\s*/\s*[0-9]+(?:[.,][0-9]+)?',
        texto, re.IGNORECASE
    )
    if m:
        v = float(m.group(1).replace(',', '.'))
        if valido(v):
            return normaliza(v)

    # Padrão 1: Soma explícita (ex: 10 + 20 + 5 = 35)
    m = re.search(r'[0-9]+(?:[^+\n=]*\+[^+\n=]*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)', texto)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if valido(v): return normaliza(v)

    # Padrão 2: Formato TOTAL/PESO (ex: 45/50) — aceita pequena variação no peso
    m = re.search(r'\[?([0-9]+(?:[.,][0-9]+)?)\]?\s*/\s*(?:' + str(int(peso_max)) + r'(?:[.,][0-9]+)?)', texto)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if valido(v): return normaliza(v)

    # Padrão 3: Palavras-chave (ex: Nota Final: 40 pontos)
    m = re.search(r'(?:nota\s*final|total|pontuação)[^:\n]*[:\→]\s*\[?([0-9]+(?:[.,][0-9]+)?)\]?', texto, re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(',', '.'))
        if valido(v): return normaliza(v)

    # Fallback: Busca o último número isolado que faça sentido no intervalo.
    # Isso é um último recurso arriscado (pode capturar números soltos do
    # texto, como quantidade de testes mencionada em um comentário) — por
    # isso fica registrado em log para permitir auditoria posterior.
    logger.warning(
        "extrair_nota_ia: nenhum padrão estruturado casou (peso_max="
        f"{peso_max}); usando fallback de último número no intervalo — "
        "resultado pode não refletir a nota real, revisar manualmente."
    )
    numeros = re.findall(r'\b([0-9]+(?:[.,][0-9]+)?)\b', texto)
    for n in reversed(numeros):
        try:
            v = float(n.replace(',', '.'))
            if valido(v): return normaliza(v)
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



def extrair_execucao_vpl_por_questao(sub_dir: Path, weights: Dict[str, int], max_chars: int = 3500) -> Dict[str, str]:
    """
    Extrai o bloco bruto de execução do VPL (casos de teste, input, saída
    produzida pelo código do aluno e saída esperada) para CADA questão.

    Isso dá à LLM evidência objetiva de corretude (o que o código realmente
    produziu quando executado), em vez de depender apenas da leitura estática
    do código — o que tende a aproximar a nota da IA da nota real do VPL.

    Retorna, por chave de questão (ex.: 'q1', 'q2'), o texto do bloco
    correspondente a '-Question N:' no execution.txt, truncado se necessário.
    """
    resultado = {k: "" for k in weights.keys()}

    ceg_dir = sub_dir.parent / f"{sub_dir.name}.ceg"
    exec_file = ceg_dir / "execution.txt"
    if not exec_file.exists():
        return resultado

    content = exec_file.read_text(errors='replace')

    # Divide o conteúdo em blocos por marcador "-Question N:" do VPL
    partes = re.split(r'-Question\s+(\d+)\s*:', content)
    # partes = [preambulo, '1', bloco1, '2', bloco2, '3', bloco3, ...]
    blocos_por_numero = {}
    for i in range(1, len(partes), 2):
        q_num_str = partes[i]
        bloco_texto = partes[i + 1] if i + 1 < len(partes) else ""
        blocos_por_numero[q_num_str] = bloco_texto.strip()

    # Mapeia na MESMA ordem usada em extrair_dados_vpl (ordem do dict weights)
    for idx, q_key in enumerate(weights.keys(), start=1):
        bloco = blocos_por_numero.get(str(idx), "")
        if bloco:
            if len(bloco) > max_chars:
                bloco = bloco[:max_chars] + "\n...[bloco truncado por tamanho]..."
            resultado[q_key] = bloco

    return resultado

def extrair_enunciado_vpl_por_questao(sub_dir: Path, weights: Dict[str, int], max_chars: int = 1500) -> Dict[str, str]:
    """
    Extrai o ENUNCIADO OFICIAL de cada questão diretamente do execution.txt
    do VPL (campo 'Descrição resumida da questão'), quando presente.

    Como as questões são sorteadas/paramétricas via MCTest, esse texto é a
    fonte de verdade sobre qual operação e variação específica caiu para
    aquele aluno — mais confiável que inferir o tipo só pela leitura estática
    do código, especialmente em código incompleto ou ambíguo entre tipos.

    Retorna, por chave de questão (ex.: 'q1', 'q2'), o enunciado extraído
    e normalizado em uma única linha (string vazia se não encontrado).
    """
    resultado = {k: "" for k in weights.keys()}

    ceg_dir = sub_dir.parent / f"{sub_dir.name}.ceg"
    exec_file = ceg_dir / "execution.txt"
    if not exec_file.exists():
        return resultado

    content = exec_file.read_text(errors='replace')

    # Mesma lógica de divisão em blocos usada em extrair_execucao_vpl_por_questao
    partes = re.split(r'-Question\s+(\d+)\s*:', content)
    blocos_por_numero = {}
    for i in range(1, len(partes), 2):
        q_num_str = partes[i]
        bloco_texto = partes[i + 1] if i + 1 < len(partes) else ""
        blocos_por_numero[q_num_str] = bloco_texto

    for idx, q_key in enumerate(weights.keys(), start=1):
        bloco = blocos_por_numero.get(str(idx), "")
        if not bloco:
            continue

        # Captura o texto entre "Descrição resumida da questão:" e o próximo
        # marcador conhecido ("Veja o exemplo...") ou o fim do bloco.
        m = re.search(
            r'-?\s*Descri[çc][ãa]o resumida da quest[ãa]o:\s*(.*?)'
            r'(?:Veja o exemplo|--\s*\|>|$)',
            bloco, re.DOTALL | re.IGNORECASE
        )
        if m:
            enunciado = m.group(1).strip()
            enunciado = re.sub(r'\s+', ' ', enunciado)  # o VPL costuma vir tudo em 1 linha só
            if len(enunciado) > max_chars:
                enunciado = enunciado[:max_chars] + "... [truncado]"
            resultado[q_key] = enunciado

    return resultado

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