"""Registro JSONL canónico y coordinación de su índice derivado."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import NoReturn

from nox_agent.audit.coordination import AuditCoordinator
from nox_agent.audit.events import AuditEvent, JsonValue
from nox_agent.audit.index import AuditIndex, DATABASE_SCHEMA_VERSION
from nox_agent.audit.session_file import AuditSessionFile
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.tools import Validator


class AuditStore:
    """Confirma JSONL antes de actualizar el índice reconstruible."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or self.default_root()
        self.sessions_path = self.root / "sessions"
        self.database_path = self.root / "audit.db"
        self._dirty_path = self.root / ".index-dirty"
        self._index = AuditIndex(self.database_path)
        self._coordinator = AuditCoordinator(self.root)

    @staticmethod
    def default_root() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                detail="Windows no informó LOCALAPPDATA.",
            )
        return Path(local_app_data) / "Nox" / "audit"

    def session_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.sessions_path / f"{session_id}.jsonl"

    def mark_active(self, session_id: str) -> None:
        path = self.session_path(session_id)
        with self._coordinator.exclusive():
            if path.exists():
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_QUERY_INVALID,
                    detail=f"La sesión {session_id} ya existe.",
                )
            self._coordinator.acquire_session(session_id)

    def mark_inactive(self, session_id: str) -> None:
        with self._coordinator.exclusive():
            self._coordinator.release_session(session_id)

    def append(self, event: AuditEvent) -> None:
        """Escribe una línea completa y deja el índice en segundo plano."""

        with self._coordinator.exclusive():
            lease = self._coordinator.owned_lease(event.session_id)
            if lease is None:
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_QUERY_INVALID,
                    detail=f"La sesión {event.session_id} no está activa.",
                )
            expected = lease.last_sequence + 1
            if event.sequence != expected:
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail=(
                        f"sequence esperado {expected}, "
                        f"recibido {event.sequence}."
                    ),
                )
            if event.event_id in lease.event_ids:
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail=f"event_id duplicado: {event.event_id}.",
                )
            if lease.ended:
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail="La sesión ya contiene session.ended.",
                )
            if expected == 1 and event.event_type != "session.started":
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail="El primer evento debe ser session.started.",
                )
            if expected > 1 and event.event_type == "session.started":
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail="session.started no puede repetirse.",
                )

            path = self.session_path(event.session_id)
            AuditSessionFile(path).append(event)

            lease.last_sequence = event.sequence
            lease.event_ids.add(event.event_id)
            lease.ended = event.event_type == "session.ended"
            try:
                self._index.append(event, path.name)
            except NoxError as error:
                self._mark_index_dirty(error)

    def synchronize(self) -> dict[str, int]:
        return self.rebuild()

    def rebuild(self) -> dict[str, int]:
        with self._coordinator.exclusive():
            return self._rebuild_locked()

    def cleanup(self, retention_hours: int) -> int:
        """Aplica retención y reconcilia SQLite con los archivos restantes."""

        if (
            isinstance(retention_hours, bool)
            or not isinstance(retention_hours, int)
            or retention_hours < 0
        ):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="retention_hours debe ser un entero no negativo.",
            )

        cutoff = time.time() - retention_hours * 60 * 60
        with self._coordinator.exclusive():
            active = self._coordinator.active_session_ids()
            files = self._session_files()
            removed: list[Path] = []
            remaining: list[Path] = []
            try:
                for path in files:
                    if path.stem in active or path.stat().st_mtime > cutoff:
                        remaining.append(path)
                    else:
                        removed.append(path)
            except OSError as error:
                self._storage_error("Evaluar retención", error)

            sessions = self._read_all(remaining)
            for path in removed:
                try:
                    path.unlink()
                except OSError as error:
                    self._storage_error(f"Eliminar {path}", error)
            self._index.rebuild(sessions)
            self._clear_index_dirty()
            return len(removed)

    def status(self) -> dict[str, object]:
        with self._coordinator.exclusive():
            result: dict[str, object] = {
                "schema_version": DATABASE_SCHEMA_VERSION,
                "root": str(self.root),
                "sessions_path": str(self.sessions_path),
                "database_path": str(self.database_path),
                "session_files": len(self._session_files()),
                "active_sessions": len(
                    self._coordinator.active_session_ids()
                ),
                "index_dirty": self._dirty_path.exists(),
            }
            result.update(self._index.status())
            return result

    def list_sessions(self, limit: int | None = None) -> list[dict[str, object]]:
        self._validate_limit(limit)
        self._synchronize_if_dirty()
        with self._coordinator.exclusive():
            return self._index.list_sessions(limit)

    def read_session(self, session_id: str) -> list[dict[str, JsonValue]]:
        path = self.session_path(session_id)
        with self._coordinator.exclusive():
            if not path.is_file():
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SESSION_NOT_FOUND,
                    detail=session_id,
                )
            return [
                event.to_dict()
                for event in AuditSessionFile(path).read_events()
            ]

    def search(
        self,
        text: str,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        self._validate_limit(limit)
        if not isinstance(text, str):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="El texto de búsqueda debe ser texto.",
            )
        self._synchronize_if_dirty()
        with self._coordinator.exclusive():
            return self._index.search(text, limit)

    def clear_all(self) -> int:
        with self._coordinator.exclusive():
            if self._coordinator.active_session_ids():
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_QUERY_INVALID,
                    detail="No se puede borrar con una sesión activa.",
                )
            files = self._session_files()
            try:
                for path in files:
                    path.unlink()
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
                self._dirty_path.unlink(missing_ok=True)
            except OSError as error:
                self._storage_error(f"Borrar {self.root}", error)
            return len(files)

    def _rebuild_locked(self) -> dict[str, int]:
        sessions = self._read_all(self._session_files())
        result = self._index.rebuild(sessions)
        self._clear_index_dirty()
        return result

    def _read_all(
        self,
        files: list[Path],
    ) -> list[tuple[Path, list[AuditEvent]]]:
        sessions: list[tuple[Path, list[AuditEvent]]] = []
        for path in files:
            events = AuditSessionFile(path).read_events()
            if events:
                sessions.append((path, events))
        return sessions

    def _session_files(self) -> list[Path]:
        if not self.sessions_path.exists():
            return []
        try:
            return sorted(
                path
                for path in self.sessions_path.glob("*.jsonl")
                if path.is_file()
            )
        except OSError as error:
            self._storage_error(f"Enumerar {self.sessions_path}", error)

    def _synchronize_if_dirty(self) -> None:
        if self._dirty_path.exists():
            self.rebuild()

    def _mark_index_dirty(self, error: NoxError) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._dirty_path.write_text(
                f"{error.code}\n",
                encoding="utf-8",
            )
        except OSError:
            # El evento ya quedó confirmado en JSONL; no se lo invalida.
            pass

    def _clear_index_dirty(self) -> None:
        try:
            self._dirty_path.unlink(missing_ok=True)
        except OSError as error:
            self._storage_error(f"Limpiar {self._dirty_path}", error)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not Validator.is_uuid(session_id):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="El identificador de sesión no es un UUID válido.",
            )

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="limit debe ser un entero no negativo o null.",
            )

    @staticmethod
    def _storage_error(operation: str, error: BaseException) -> NoReturn:
        raise NoxErrorFactory.create(
            ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
            detail=f"{operation}: {error}",
        ) from error
