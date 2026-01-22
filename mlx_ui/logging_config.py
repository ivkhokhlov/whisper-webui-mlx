from __future__ import annotations

import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler


def configure_logging(base_dir: Path | None = None) -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_mlx_ui_configured", False):
        return

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    log_dir = Path(os.getenv("LOG_DIR", base_dir / "data" / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(level_name)
    if isinstance(level, str):
        level = logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_dir / "mlx-ui.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    root_logger._mlx_ui_configured = True
