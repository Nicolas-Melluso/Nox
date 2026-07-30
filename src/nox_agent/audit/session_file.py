"""Lectura y escritura durable de una sesión JSONL canónica."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from nox_agent.audit.events import AuditEvent
from nox_agent.errors import ErrorCode, NoxErrorFactory


@dataclass(frozen=True, slots=True)
class AuditSessionFile:
    """Opera un JSONL; el llamador debe aportar la coordinación necesaria."""

    path: Path

    def append(self, event: AuditEvent) -> None:
        serialized = (
            json.dumps(
                event.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

        self._trim_truncated_tail()
        existed = self.path.exists()
        try:
            original_size = self.path.stat().st_size if existed else 0
        except OSError as error:
            self._storage_error(f"Consultar {self.path}", error)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab", buffering=0) as output:
                if output.write(serialized) != len(serialized):
                    raise OSError("La escritura quedó incompleta.")
                output.flush()
                os.fsync(output.fileno())
        except OSError as error:
            rollback_error = self._rollback(existed, original_size)
            detail = f"Escribir {self.path}: {error}"
            if rollback_error is not None:
                detail += f"; rollback falló: {rollback_error}"
            self._storage_error(detail, error)

    def read_events(self) -> list[AuditEvent]:
        events: list[AuditEvent] = []
        event_ids: set[str] = set()
        ended = False

        try:
            with self.path.open("rb") as source:
                for line_number, raw_line in enumerate(source, start=1):
                    if not raw_line.endswith(b"\n"):
                        # Sólo se tolera la última línea sin delimitador.
                        break
                    try:
                        value = json.loads(raw_line.decode("utf-8"))
                        if not isinstance(value, dict):
                            raise ValueError("la línea no contiene un objeto")
                        event = AuditEvent.from_dict(value)
                        if event.session_id != self.path.stem:
                            raise ValueError(
                                "session_id no coincide con el archivo"
                            )
                        expected = len(events) + 1
                        if event.sequence != expected:
                            raise ValueError(
                                f"sequence esperado {expected}, "
                                f"recibido {event.sequence}"
                            )
                        if event.event_id in event_ids:
                            raise ValueError(
                                f"event_id duplicado: {event.event_id}"
                            )
                        if expected == 1 and event.event_type != "session.started":
                            raise ValueError(
                                "el primer evento no es session.started"
                            )
                        if expected > 1 and event.event_type == "session.started":
                            raise ValueError("session.started está duplicado")
                        if ended:
                            raise ValueError(
                                "hay eventos posteriores a session.ended"
                            )
                        ended = event.event_type == "session.ended"
                        event_ids.add(event.event_id)
                        events.append(event)
                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ) as error:
                        raise NoxErrorFactory.create(
                            ErrorCode.AUDIT_SCHEMA_INVALID,
                            detail=(
                                f"{self.path}, línea {line_number}: {error}"
                            ),
                        ) from error
        except OSError as error:
            self._storage_error(f"Leer {self.path}", error)
        return events

    def _trim_truncated_tail(self) -> None:
        """Descarta bytes posteriores al último delimitador confirmado."""

        if not self.path.exists():
            return
        try:
            with self.path.open("r+b", buffering=0) as output:
                output.seek(0, os.SEEK_END)
                size = output.tell()
                if size == 0:
                    return
                output.seek(-1, os.SEEK_END)
                if output.read(1) == b"\n":
                    return
                confirmed_size = 0
                position = size
                while position > 0:
                    chunk_size = min(8_192, position)
                    position -= chunk_size
                    output.seek(position)
                    chunk = output.read(chunk_size)
                    newline = chunk.rfind(b"\n")
                    if newline >= 0:
                        confirmed_size = position + newline + 1
                        break
                output.truncate(confirmed_size)
                output.flush()
                os.fsync(output.fileno())
        except OSError as error:
            self._storage_error(
                f"Reparar cola truncada de {self.path}",
                error,
            )

    def _rollback(
        self,
        existed: bool,
        original_size: int,
    ) -> OSError | None:
        try:
            if not existed:
                self.path.unlink(missing_ok=True)
                return None
            with self.path.open("r+b", buffering=0) as output:
                output.truncate(original_size)
                output.flush()
                os.fsync(output.fileno())
        except OSError as error:
            return error
        return None

    @staticmethod
    def _storage_error(operation: str, error: BaseException) -> NoReturn:
        raise NoxErrorFactory.create(
            ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
            detail=f"{operation}: {error}",
        ) from error
