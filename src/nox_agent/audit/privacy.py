"""Selección de detalle y redacción defensiva de datos auditados."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from nox_agent.audit.events import JsonValue

REDACTED = "[REDACTED]"
UNSUPPORTED = "[UNSUPPORTED]"
MAX_DATA_DEPTH = 12


class AuditLevel(StrEnum):
    """Capas acumulativas de datos que puede conservar un evento."""

    OFF = "off"
    METADATA = "metadata"
    ACTIVITY = "activity"
    FULL = "full"


class AuditPrivacy:
    """Aplica el nivel elegido y evita secretos o razonamiento interno."""

    @classmethod
    def select_data(
        cls,
        level: AuditLevel,
        metadata: Mapping[str, object] | None,
        activity: Mapping[str, object] | None,
        full: Mapping[str, object] | None,
    ) -> dict[str, JsonValue]:
        data: dict[str, JsonValue] = {}
        if level == AuditLevel.OFF:
            return data
        if metadata:
            data["metadata"] = cls.sanitize_mapping(metadata)
        if level in (AuditLevel.ACTIVITY, AuditLevel.FULL) and activity:
            data["activity"] = cls.sanitize_mapping(activity)
        if level == AuditLevel.FULL and full:
            data["full"] = cls.sanitize_mapping(full)
        return data

    @classmethod
    def sanitize_mapping(
        cls,
        value: Mapping[str, object],
    ) -> dict[str, JsonValue]:
        sanitized = cls._sanitize(value, depth=0)
        return sanitized if isinstance(sanitized, dict) else {}

    @classmethod
    def _sanitize(cls, value: object, *, depth: int) -> JsonValue:
        if depth >= MAX_DATA_DEPTH:
            return "[MAX_DEPTH]"
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            result: dict[str, JsonValue] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized = "".join(
                    character
                    for character in key.casefold()
                    if character.isalnum()
                )
                if cls._is_private_key(normalized):
                    result[key] = REDACTED
                else:
                    result[key] = cls._sanitize(item, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item, depth=depth + 1) for item in value]
        if isinstance(value, bytes):
            return REDACTED
        return f"{UNSUPPORTED}:{type(value).__name__}"

    @classmethod
    def _is_private_key(cls, key: str) -> bool:
        return cls._is_reasoning_key(key) or cls._is_sensitive_key(key)

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        if key in {
            "inputtokens",
            "outputtokens",
            "totaltokens",
            "tokencount",
        }:
            return False
        return any(
            fragment in key
            for fragment in (
                "authorization",
                "password",
                "passwd",
                "secret",
                "apikey",
                "accesstoken",
                "refreshtoken",
                "credential",
                "cookie",
                "privatekey",
            )
        )

    @staticmethod
    def _is_reasoning_key(key: str) -> bool:
        return key in {
            "reasoning",
            "chainofthought",
            "internalreasoning",
            "hiddenreasoning",
            "thinking",
        }
