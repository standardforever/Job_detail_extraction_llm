from __future__ import annotations

import logging
from pathlib import Path


LOG_FILE_PATH = Path(__file__).resolve().parents[2] / "job_process.log"


def configure_logging() -> None:
    root_logger = logging.getLogger("job_pipeline")
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"job_pipeline.{name}")
