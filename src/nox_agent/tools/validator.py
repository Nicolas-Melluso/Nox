"""Validaciones genéricas y sin estado utilizadas por Nox."""

from datetime import datetime, timezone
from pathlib import Path
from typing import TypeGuard
from uuid import UUID


class Validator:
    """Agrupa validaciones reutilizables que no modifican sus entradas."""

    @staticmethod
    def is_uuid(value: object) -> TypeGuard[str]:
        if not isinstance(value, str):
            return False
        try:
            UUID(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def is_utc_datetime(value: object) -> TypeGuard[str]:
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            parsed.tzinfo is not None
            and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
        )

    @staticmethod
    def is_non_empty_string(value: object) -> TypeGuard[str]:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def is_relative_path(value: object) -> TypeGuard[str]:
        return (
            isinstance(value, str)
            and bool(value.strip())
            and not Path(value).is_absolute()
        )
