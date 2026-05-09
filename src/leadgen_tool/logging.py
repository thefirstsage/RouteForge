from __future__ import annotations

import logging
from pathlib import Path

from leadgen_tool.config import app_data_dir


def configure_logging() -> logging.Logger:
    log_dir = app_data_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        log_dir = _workspace_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    logger = logging.getLogger("leadgen_tool")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            handler = logging.FileHandler(log_path, encoding="utf-8")
        except PermissionError:
            fallback_dir = _workspace_log_dir()
            fallback_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(fallback_dir / "app.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)

    return logger


def _workspace_log_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "logs"
