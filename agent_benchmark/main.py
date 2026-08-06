import argparse
from datetime import datetime
from pathlib import Path

from agent_benchmark.agent import BenchmarkAgent
from agent_benchmark.report_generator import generer_rapport
from config.settings import settings
from core.llm_client import get_llm_client
from core.logger import get_logger
from core.storage import JSONStorage

logger = get_logger(__name__)


def run(cible: str) -> str:
    llm = get_llm_client()
    agent = BenchmarkAgent(llm)
    entites = agent.run(cible)

    storage = JSONStorage()
    nom_fichier = f"benchmark_{cible.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}"
    storage.save(entites, nom_fichier)

    rapport = generer_rapport(llm, cible, entites)
    (Path(settings.output_dir) / f"{nom_fichier}_rapport.md").write_text(rapport, encoding="utf-8")

    logger.info(f"Terminé : {len(entites)} entité(s)")
    return rapport


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Étude Benchmark")
    parser.add_argument("--cible", required=True)
    args = parser.parse_args()
    run(args.cible)
