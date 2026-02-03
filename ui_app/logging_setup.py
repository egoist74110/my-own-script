from __future__ import annotations

import logging
from pathlib import Path

from runner_app.config import data_dir


def setup_app_logger() -> logging.Logger:
    dd = data_dir()
    dd.mkdir(parents=True, exist_ok=True)
    log_path = dd / "ui.log"

    logger = logging.getLogger("my-own-script")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)

        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)

        logger.addHandler(fh)
        logger.addHandler(sh)

    return logger
