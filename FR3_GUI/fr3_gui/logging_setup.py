"""Centralized logging: console + rotating file under logs/."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import app_data_dir

LOG_DIR = app_data_dir() / "logs"
LOG_FILE = LOG_DIR / "fr3_gui.log"


def configure_logging(level: int = logging.DEBUG) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info("Logging started - writing to %s", LOG_FILE)
