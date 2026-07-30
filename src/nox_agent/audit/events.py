"""Estructura estable de los eventos persistidos por la auditoría."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, TypeAlias, cast
from uuid import uuid4

from nox_agent.tools import Validator

AUDIT_SCHEMA_VERSION = 1

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class AuditCategory(StrEnum):
    """Canales de auditoría que se habilitan de manera independiente."""

    AUDIT = "audit"
    TRANSCRIPT = "transcript"
    METRIC = "metric"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Evento común e inmutable que se escribe como una línea JSON."""

    schema_version: int
    event_id: str
    sequence: int
    category: str
    event_type: str
    occurred_at_utc: str
    session_id: str
    interaction_id: str | None
    operation_id: str | None
    parent_event_id: str | None
    execution_mode: str
    duration_ms: int | None
    data: dict[str, JsonValue]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != AUDIT_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Versión de evento no compatible: {self.schema_version}."
            )
        _validate_uuid(self.event_id, "event_id")
        _validate_uuid(self.session_id, "session_id")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("sequence debe ser un entero mayor o igual a 1.")
        _validate_text(self.category, "category")
        try:
            AuditCategory(self.category)
        except ValueError as error:
            raise ValueError(
                f"category no reconocida: {self.category}."
            ) from error
        _validate_text(self.event_type, "event_type")
        _validate_utc_datetime(self.occurred_at_utc)
        _validate_optional_text(self.interaction_id, "interaction_id")
        _validate_optional_text(self.operation_id, "operation_id")
        _validate_optional_uuid(self.parent_event_id, "parent_event_id")
        _validate_text(self.execution_mode, "execution_mode")
        if self.duration_ms is not None:
            if (
                isinstance(self.duration_ms, bool)
                or not isinstance(self.duration_ms, int)
                or self.duration_ms < 0
            ):
                raise ValueError("duration_ms debe ser un entero no negativo.")
        _validate_json_value(self.data, "data")

    def to_dict(self) -> dict[str, JsonValue]:
        """Devuelve el contrato serializable respetando su orden estable."""

        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "category": self.category,
            "event_type": self.event_type,
            "occurred_at_utc": self.occurred_at_utc,
            "session_id": self.session_id,
            "interaction_id": self.interaction_id,
            "operation_id": self.operation_id,
            "parent_event_id": self.parent_event_id,
            "execution_mode": self.execution_mode,
            "duration_ms": self.duration_ms,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AuditEvent":
        """Valida un evento leído desde el registro canónico."""

        data = value.get("data")
        if not isinstance(data, dict):
            raise ValueError("data debe ser un objeto JSON.")
        _validate_json_value(data, "data")

        return cls(
            schema_version=_required_int(value, "schema_version"),
            event_id=_required_text(value, "event_id"),
            sequence=_required_int(value, "sequence"),
            category=_required_text(value, "category"),
            event_type=_required_text(value, "event_type"),
            occurred_at_utc=_required_text(value, "occurred_at_utc"),
            session_id=_required_text(value, "session_id"),
            interaction_id=_optional_text(value, "interaction_id"),
            operation_id=_optional_text(value, "operation_id"),
            parent_event_id=_optional_text(value, "parent_event_id"),
            execution_mode=_required_text(value, "execution_mode"),
            duration_ms=_optional_int(value, "duration_ms"),
            data=cast(dict[str, JsonValue], dict(data)),
        )


class AuditEventFactory:
    """Crea eventos sin distribuir UUID y tiempo de pared por el código."""

    @staticmethod
    def create(
        *,
        sequence: int,
        category: AuditCategory | str,
        event_type: str,
        session_id: str,
        execution_mode: str,
        interaction_id: str | None = None,
        operation_id: str | None = None,
        parent_event_id: str | None = None,
        duration_ms: int | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            schema_version=AUDIT_SCHEMA_VERSION,
            event_id=str(uuid4()),
            sequence=sequence,
            category=str(category),
            event_type=event_type,
            occurred_at_utc=_utc_now(),
            session_id=session_id,
            interaction_id=interaction_id,
            operation_id=operation_id,
            parent_event_id=parent_event_id,
            execution_mode=execution_mode,
            duration_ms=duration_ms,
            data=dict(data or {}),
        )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _validate_uuid(value: str, field: str) -> None:
    if not Validator.is_uuid(value):
        raise ValueError(f"{field} debe ser un UUID válido.")


def _validate_optional_uuid(value: str | None, field: str) -> None:
    if value is not None:
        _validate_uuid(value, field)


def _validate_text(value: str, field: str) -> None:
    if not Validator.is_non_empty_string(value):
        raise ValueError(f"{field} debe ser un texto no vacío.")


def _validate_optional_text(value: str | None, field: str) -> None:
    if value is not None:
        _validate_text(value, field)


def _validate_utc_datetime(value: str) -> None:
    if not value.endswith("Z") or not Validator.is_utc_datetime(value):
        raise ValueError("occurred_at_utc debe usar UTC y terminar en Z.")


def _validate_json_value(value: object, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} no puede contener NaN o infinito.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field} sólo puede contener claves de texto.")
            _validate_json_value(item, f"{field}.{key}")
        return
    raise ValueError(f"{field} contiene un valor que no pertenece a JSON.")


def _required_text(value: Mapping[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str):
        raise ValueError(f"{field} debe ser un texto.")
    return result


def _optional_text(value: Mapping[str, object], field: str) -> str | None:
    result = value.get(field)
    if result is None:
        return None
    if not isinstance(result, str):
        raise ValueError(f"{field} debe ser un texto o null.")
    return result


def _required_int(value: Mapping[str, object], field: str) -> int:
    result = value.get(field)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"{field} debe ser un entero.")
    return result


def _optional_int(value: Mapping[str, object], field: str) -> int | None:
    result = value.get(field)
    if result is None:
        return None
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"{field} debe ser un entero o null.")
    return result
