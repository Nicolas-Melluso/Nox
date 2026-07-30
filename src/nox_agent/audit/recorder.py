"""Ciclo de vida y canales de una sesión auditada."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import NoReturn
from uuid import uuid4

from nox_agent.audit.events import AuditCategory, AuditEvent, AuditEventFactory
from nox_agent.audit.privacy import AuditLevel, AuditPrivacy
from nox_agent.audit.store import AuditStore
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.feature_flags import FeatureFlagManager


@dataclass(frozen=True, slots=True)
class AuditRecorderSettings:
    enabled: bool
    level: AuditLevel
    retention_hours: int
    transcription_enabled: bool
    metrics_enabled: bool
    metric_timings_enabled: bool


class AuditRecorder:
    """Registra eventos autorizados sin exponer su persistencia."""

    def __init__(
        self,
        start: Path,
        *,
        execution_mode: str = "interactive",
        session_metadata: Mapping[str, object] | None = None,
        store: AuditStore | None = None,
        session_id: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = self._load_settings(start)
        self.session_id = session_id or str(uuid4())
        self.execution_mode = execution_mode
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._sequence = 0
        self._closed = False
        self._lock = threading.RLock()
        self.store = store if self.settings.enabled else None

        if not self.settings.enabled:
            return
        if self.store is None:
            self.store = AuditStore()
        self.store.cleanup(self.settings.retention_hours)
        self.store.mark_active(self.session_id)
        try:
            self._record(
                AuditCategory.AUDIT,
                "session.started",
                metadata={
                    "audit_level": self.settings.level.value,
                    **dict(session_metadata or {}),
                },
            )
        except Exception:
            self.store.mark_inactive(self.session_id)
            raise

    def audit(
        self,
        event_type: str,
        **event: object,
    ) -> AuditEvent | None:
        self._validate_public_event_type(event_type)
        return self._record(AuditCategory.AUDIT, event_type, **event)

    def transcript(
        self,
        event_type: str,
        **event: object,
    ) -> AuditEvent | None:
        self._validate_public_event_type(event_type)
        if not self.settings.transcription_enabled:
            return None
        if any(
            fragment in event_type.casefold()
            for fragment in ("token", "chunk", "delta")
        ):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="La transcripción sólo admite mensajes completos.",
            )
        return self._record(AuditCategory.TRANSCRIPT, event_type, **event)

    def metric(
        self,
        event_type: str,
        **event: object,
    ) -> AuditEvent | None:
        self._validate_public_event_type(event_type)
        if not self.settings.metrics_enabled:
            return None
        duration = event.get("duration_ms")
        if duration is not None and not self.settings.metric_timings_enabled:
            return None
        return self._record(AuditCategory.METRIC, event_type, **event)

    def close(
        self,
        *,
        outcome: str = "success",
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent | None:
        """Cierra una sola vez y mide la sesión con reloj monotónico."""

        with self._lock:
            if self._closed:
                return None
            if not self.settings.enabled or self.store is None:
                self._closed = True
                return None
            duration_ms = max(
                0,
                round((self._monotonic() - self._started_at) * 1000),
            )
            event = self._record(
                AuditCategory.AUDIT,
                "session.ended",
                metadata={"outcome": outcome, **dict(metadata or {})},
                duration_ms=duration_ms,
            )
            self._closed = True
            self.store.mark_inactive(self.session_id)
            return event

    def __enter__(self) -> "AuditRecorder":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        metadata = (
            {"error_type": type(exception).__name__}
            if exception is not None
            else None
        )
        self.close(
            outcome="error" if exception is not None else "success",
            metadata=metadata,
        )

    def _record(
        self,
        category: AuditCategory,
        event_type: str,
        *,
        metadata: object = None,
        activity: object = None,
        full: object = None,
        interaction_id: object = None,
        operation_id: object = None,
        parent_event_id: object = None,
        duration_ms: object = None,
        **unknown: object,
    ) -> AuditEvent | None:
        if unknown:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail=f"Campos de evento desconocidos: {', '.join(unknown)}.",
            )
        if not self.settings.enabled or self.store is None:
            return None
        with self._lock:
            if self._closed and event_type != "session.ended":
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_QUERY_INVALID,
                    detail="La sesión de auditoría ya está cerrada.",
                )
            next_sequence = self._sequence + 1
            event = AuditEventFactory.create(
                sequence=next_sequence,
                category=category,
                event_type=event_type,
                session_id=self.session_id,
                execution_mode=self.execution_mode,
                interaction_id=_optional_text(interaction_id, "interaction_id"),
                operation_id=_optional_text(operation_id, "operation_id"),
                parent_event_id=_optional_text(
                    parent_event_id,
                    "parent_event_id",
                ),
                duration_ms=_optional_int(duration_ms, "duration_ms"),
                data=AuditPrivacy.select_data(
                    self.settings.level,
                    _optional_mapping(metadata, "metadata"),
                    _optional_mapping(activity, "activity"),
                    _optional_mapping(full, "full"),
                ),
            )
            self.store.append(event)
            self._sequence = next_sequence
            return event

    @staticmethod
    def _validate_public_event_type(event_type: str) -> None:
        if event_type in {"session.started", "session.ended"}:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail=f"{event_type} es administrado por AuditRecorder.",
            )

    @staticmethod
    def _load_settings(start: Path) -> AuditRecorderSettings:
        effective = FeatureFlagManager(start).effective()
        requested = _flag_bool(effective.get("audit.enabled"), "audit.enabled")
        level_value = effective.get("audit.level")
        if not isinstance(level_value, str):
            _invalid_flag("audit.level debe ser un texto.")
        try:
            level = AuditLevel(level_value)
        except ValueError as error:
            raise NoxErrorFactory.create(
                ErrorCode.FEATURE_FLAGS_INVALID,
                detail="audit.level debe ser off, metadata, activity o full.",
            ) from error

        retention = effective.get("audit.retention_hours")
        if isinstance(retention, bool) or not isinstance(retention, int) or retention < 0:
            _invalid_flag(
                "audit.retention_hours debe ser un entero no negativo."
            )
        return AuditRecorderSettings(
            enabled=requested and level != AuditLevel.OFF,
            level=level,
            retention_hours=retention,
            transcription_enabled=_flag_bool(
                effective.get("transcription.enabled"),
                "transcription.enabled",
            ),
            metrics_enabled=_flag_bool(
                effective.get("metrics.enabled"),
                "metrics.enabled",
            ),
            metric_timings_enabled=_flag_bool(
                effective.get("metrics.timings"),
                "metrics.timings",
            ),
        )


def _flag_bool(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        _invalid_flag(f"{key} debe ser true o false.")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    _invalid_event(f"{field} debe ser texto o null.")


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    _invalid_event(f"{field} debe ser entero o null.")


def _optional_mapping(
    value: object,
    field: str,
) -> Mapping[str, object] | None:
    if value is None or isinstance(value, Mapping):
        return value
    _invalid_event(f"{field} debe ser un objeto o null.")


def _invalid_flag(detail: str) -> NoReturn:
    raise NoxErrorFactory.create(ErrorCode.FEATURE_FLAGS_INVALID, detail=detail)


def _invalid_event(detail: str) -> NoReturn:
    raise NoxErrorFactory.create(ErrorCode.AUDIT_QUERY_INVALID, detail=detail)
