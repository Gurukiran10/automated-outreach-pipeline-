"""Structured logger with Rich console output and rotating file handler."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from src.config import get_app

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    cfg = get_app()
    cfg.ensure_dirs()

    logger = logging.getLogger(name)
    logger.setLevel(cfg.log_level)
    logger.propagate = False

    if not logger.handlers:
        # Rich console handler
        console = RichHandler(
            rich_tracebacks=True,
            markup=True,
            show_path=False,
        )
        console.setLevel(cfg.log_level)
        logger.addHandler(console)

        # Rotating file handler (10 MB × 5 backups)
        log_file = cfg.log_dir / "pipeline.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        file_handler.setLevel(cfg.log_level)
        logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger
