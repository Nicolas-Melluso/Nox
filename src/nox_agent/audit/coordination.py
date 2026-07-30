"""Locks interproceso y leases de sesión para la auditoría."""

from __future__ import annotations

import importlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.tools import Validator

if os.name == "nt":
    msvcrt = importlib.import_module("msvcrt")
    fcntl = None
else:  # pragma: no cover - compatibilidad para desarrollo POSIX
    msvcrt = None
    fcntl = importlib.import_module("fcntl")

LOCK_TIMEOUT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 0.05

_registry_lock = threading.RLock()
_thread_locks: dict[str, threading.RLock] = {}
_leases: dict[tuple[str, str], "SessionLease"] = {}


@dataclass(slots=True)
class SessionLease:
    """Lock vivo y estado canónico conocido de una sesión del proceso."""

    session_id: str
    path: Path
    handle: BinaryIO
    last_sequence: int = 0
    event_ids: set[str] = field(default_factory=set)
    ended: bool = False


class AuditCoordinator:
    """Serializa operaciones y detecta sesiones vivas entre procesos."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root_key = os.path.normcase(str(root.resolve()))
        self.lock_path = root / ".audit.lock"
        self.leases_path = root / "leases"
        with _registry_lock:
            self._thread_lock = _thread_locks.setdefault(
                self.root_key,
                threading.RLock(),
            )

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Adquiere el lock estructural del directorio de auditoría."""

        with self._thread_lock:
            handle: BinaryIO | None = None
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                handle = self.lock_path.open("a+b")
                _ensure_lock_byte(handle)
            except OSError as error:
                if handle is not None:
                    handle.close()
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                    detail=f"Abrir lock de auditoría {self.lock_path}: {error}",
                ) from error

            assert handle is not None
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            try:
                while not _try_lock(handle):
                    if time.monotonic() >= deadline:
                        raise NoxErrorFactory.create(
                            ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                            detail=(
                                "La auditoría está ocupada por otro proceso "
                                f"durante más de {LOCK_TIMEOUT_SECONDS:g} segundos."
                            ),
                        )
                    time.sleep(LOCK_RETRY_SECONDS)
                yield
            finally:
                try:
                    _unlock(handle)
                except OSError:
                    pass
                handle.close()

    def acquire_session(self, session_id: str) -> SessionLease:
        """Reserva un identificador hasta `release_session` o fin del proceso."""

        if not Validator.is_uuid(session_id):
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="El identificador de sesión no es un UUID válido.",
            )
        key = (self.root_key, session_id)
        with _registry_lock:
            if key in _leases:
                self._duplicate_session(session_id)

        handle: BinaryIO | None = None
        try:
            self.leases_path.mkdir(parents=True, exist_ok=True)
            path = self.leases_path / f"{session_id}.lock"
            handle = path.open("a+b")
            _ensure_lock_byte(handle)
        except OSError as error:
            if handle is not None:
                handle.close()
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                detail=f"Crear lease de sesión {session_id}: {error}",
            ) from error

        assert handle is not None
        if not _try_lock(handle):
            handle.close()
            self._duplicate_session(session_id)

        lease = SessionLease(session_id, path, handle)
        with _registry_lock:
            if key in _leases:
                _unlock(handle)
                handle.close()
                self._duplicate_session(session_id)
            _leases[key] = lease
        return lease

    def release_session(self, session_id: str) -> None:
        key = (self.root_key, session_id)
        with _registry_lock:
            lease = _leases.pop(key, None)
        if lease is None:
            return
        try:
            _unlock(lease.handle)
        finally:
            lease.handle.close()
        try:
            lease.path.unlink(missing_ok=True)
        except OSError:
            # Un archivo de lease sin lock se reconoce como inactivo y es inocuo.
            pass

    def owned_lease(self, session_id: str) -> SessionLease | None:
        with _registry_lock:
            return _leases.get((self.root_key, session_id))

    def active_session_ids(self) -> set[str]:
        """Consulta leases vivos; los archivos abandonados no cuentan."""

        with _registry_lock:
            active = {
                session_id
                for (root, session_id), _lease in _leases.items()
                if root == self.root_key
            }
        if not self.leases_path.exists():
            return active

        try:
            paths = list(self.leases_path.glob("*.lock"))
        except OSError as error:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                detail=f"Enumerar leases en {self.leases_path}: {error}",
            ) from error

        for path in paths:
            session_id = path.stem
            if session_id in active or not Validator.is_uuid(session_id):
                continue
            try:
                handle = path.open("a+b")
                _ensure_lock_byte(handle)
            except OSError as error:
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                    detail=f"Consultar lease {path}: {error}",
                ) from error
            if _try_lock(handle):
                _unlock(handle)
                handle.close()
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                handle.close()
                active.add(session_id)
        return active

    @staticmethod
    def _duplicate_session(session_id: str) -> None:
        raise NoxErrorFactory.create(
            ErrorCode.AUDIT_QUERY_INVALID,
            detail=f"La sesión {session_id} ya está activa.",
        )


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if msvcrt is not None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - plataforma sin mecanismo compatible
            raise OSError("La plataforma no ofrece locks de archivo.")
    except OSError:
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if msvcrt is not None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    elif fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
