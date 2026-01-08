from __future__ import annotations

import logging
from typing import Optional


def get_logger(name: str = "pipeline") -> logging.Logger:
    """Return a configured logger.

    Uses INFO level by default. Avoids duplicate handlers when imported
    repeatedly in notebooks or scripts.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_step(step: int | str, label: Optional[str] = None, *, logger: Optional[logging.Logger] = None) -> None:
    """Log a simple step banner for progress visibility."""
    msg = f" Step {label if label is not None else step} "
    line = "-" * 15
    if logger is None:
        print(line, msg, line)
    else:
        logger.info("%s%s%s", line, msg, line)

