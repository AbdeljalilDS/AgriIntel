import logging
import sys
from pathlib import Path


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # StreamHandler avec encodage UTF-8 forcé (évite UnicodeEncodeError sur Windows cp1252)
    try:
        console_handler = logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
        )
    except Exception:
        # Fallback si fileno() n'est pas disponible (ex: dans certains IDE)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setStream(sys.stdout)

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
