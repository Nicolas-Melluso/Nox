"""Configuración central del sistema de logs de Nox."""

import logging
from enum import StrEnum
from typing import TextIO

LOGGER_NAME = "nox"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NoxLogs:
    """Entrega loggers y habilita su salida cuando Nox lo solicita."""

    @staticmethod
    def get_logger(component: str | None = None) -> logging.Logger:
        name = LOGGER_NAME if component is None else f"{LOGGER_NAME}.{component}"
        return logging.getLogger(name)

    @staticmethod
    def configure(
        level: LogLevel = LogLevel.INFO,
        *,
        stream: TextIO | None = None,
    ) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        logger.handlers.clear()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(level.value)
        logger.propagate = False


logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())
