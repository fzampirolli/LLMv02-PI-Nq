import csv
import yaml
import argparse
import asyncio
import logging
from pathlib import Path
from providers import get_client
from core.grader import process_student, save_consolidated_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

async def run_grading():
    parser = argparse.ArgumentParser(description="Sistema de Correção de Provas com IA")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--concurrent", type=int)
    args = parser.parse_args()

    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"❌ Erro ao carregar {args.config}: {e}")
        return

    client = get_client(config)
    base_dir = Path(config['paths'].get('student_base_dir', 'students'))
    if not base_dir.exists():
        logger.error(f"❌ Pasta de alunos não encontrada: {base_dir}")
        return

    student_paths = sorted([d for d in base_dir.iterdir() if d.is_dir()])
    max_concurrent = args.concurrent or config.get('max_concurrent', 3)
    semaphore = asyncio.Semaphore(max_concurrent)
    
    logger.info(f"🚀 Iniciando correção de {len(student_paths)} alunos (Máx. {max_concurrent} simultâneos)")

    # --- EXECUÇÃO ---
    tasks = [process_student(path, client, config, semaphore) for path in student_paths]
    raw_results = await asyncio.gather(*tasks) # Aguarda a conclusão de todos
    
    # Filtrar apenas os que deram certo

    results = [r for r in raw_results if r and r.get('status') == 'ok']

    csv_path = base_dir.parent / f"{base_dir.name}_relatorio.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        q_keys = sorted(config['grading']['weights'].keys())
        
        # Cabeçalho: Nome, Login, Moodle_Q1, Moodle_Q2..., IA_Q1, IA_Q2..., Total_Moodle, Total_IA, Diff
        header = ["Nome", "Login"]
        for q in q_keys: header.append(f"{q.upper()}_Moodle")
        for q in q_keys: header.append(f"{q.upper()}_IA")
        header += ["Total_Moodle", "Total_IA", "Diferenca"]
        writer.writerow(header)

        for r in results:
            partes = r['student'].split(" - ")
            nome = partes[0]
            login = partes[1] if len(partes) > 1 else ""
            
            # Monta a linha começando com as duas colunas
            row = [nome, login]
            
            # Adiciona as notas (usando int() para não ter decimais como você pediu antes)
            for q in q_keys: 
                row.append(int(r['moodle_parciais'].get(q, 0)))
            for q in q_keys: 
                row.append(int(r['ia_parciais'].get(q, 0)))
                
            row += [
                int(r.get('moodle_total', 0)), 
                int(r.get('ia_total', 0)), 
                int(r.get('diff', 0))
            ]
            writer.writerow(row)

    logger.info(f"📊 Relatório CSV gerado: {csv_path}")
    logger.info(f"✅ Processamento concluído! {len(results)}/{len(student_paths)} alunos.")

if __name__ == "__main__":
    asyncio.run(run_grading())