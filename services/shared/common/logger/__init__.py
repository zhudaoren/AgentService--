import logging
import sys
from logging import Logger
from typing import Optional

from ..config import settings


def get_logger(name: str, level: Optional[str] = None) -> Logger:
    """获取结构化日志器"""
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(level or settings.LOG_LEVEL.upper())

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.propagate = False

    return logger
