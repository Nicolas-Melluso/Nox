"""Configuración central del sistema de logs de Nox."""

import logging
import math
import os
from enum import StrEnum
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import TextIO

LOGGER_NAME = "nox"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILENAME = "nox.log"


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
        enabled: bool = True,
        console: bool = True,
        persistent: bool = False,
        retention_hours: int = 24,
    ) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        for existing_handler in logger.handlers:
            existing_handler.close()
        logger.handlers.clear()
        formatter = logging.Formatter(LOG_FORMAT)

        if enabled and console:
            handler = logging.StreamHandler(stream)
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        if enabled and persistent:
            path = NoxLogs.path()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = TimedRotatingFileHandler(
                path,
                when="h",
                interval=1,
                backupCount=max(1, math.ceil(retention_hours)),
                encoding="utf-8",
                delay=True,
                utc=True,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        logger.setLevel(level.value)
        logger.propagate = False

    @staticmethod
    def set_level(level: LogLevel) -> None:
        """Cambia el nivel sin descartar destinos ya configurados."""

        logging.getLogger(LOGGER_NAME).setLevel(level.value)

    @staticmethod
    def path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise OSError("Windows no informó la ubicación LOCALAPPDATA.")
        return Path(local_app_data) / "Nox" / "logs" / LOG_FILENAME


logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())
