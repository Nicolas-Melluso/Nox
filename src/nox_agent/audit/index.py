"""Índice SQLite reconstruible de las sesiones JSONL."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NoReturn

from nox_agent.audit.events import AUDIT_SCHEMA_VERSION, AuditEvent
from nox_agent.errors import ErrorCode, NoxErrorFactory

BUSY_TIMEOUT_MILLISECONDS = 5_000
DATABASE_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    status TEXT NOT NULL,
    file_name TEXT NOT NULL UNIQUE,
    execution_mode TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    last_sequence INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    interaction_id TEXT,
    operation_id TEXT,
    parent_event_id TEXT,
    execution_mode TEXT NOT NULL,
    duration_ms INTEGER,
    data_json TEXT NOT NULL,
    search_text TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);
CREATE INDEX IF NOT EXISTS events_session_sequence
ON events(session_id, sequence);
CREATE INDEX IF NOT EXISTS events_occurred_at ON events(occurred_at_utc);
CREATE INDEX IF NOT EXISTS events_type ON events(event_type);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    event_type,
    search_text,
    content='events',
    content_rowid='rowid',
    tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS events_after_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, event_type, search_text)
    VALUES (new.rowid, new.event_type, new.search_text);
END;
CREATE TRIGGER IF NOT EXISTS events_after_delete AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, event_type, search_text)
    VALUES ('delete', old.rowid, old.event_type, old.search_text);
END;
CREATE TRIGGER IF NOT EXISTS events_after_update AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, event_type, search_text)
    VALUES ('delete', old.rowid, old.event_type, old.search_text);
    INSERT INTO events_fts(rowid, event_type, search_text)
    VALUES (new.rowid, new.event_type, new.search_text);
END;
"""


class AuditIndex:
    """Mantiene búsquedas y resúmenes sin convertirse en fuente de verdad."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def append(self, event: AuditEvent, file_name: str) -> None:
        try:
            with self._connection() as connection:
                self._index_event(connection, event, file_name)
        except sqlite3.IntegrityError as error:
            self._schema_error(error)
        except sqlite3.Error as error:
            self._storage_error("Actualizar el índice", error)

    def rebuild(
        self,
        sessions: list[tuple[Path, list[AuditEvent]]],
    ) -> dict[str, int]:
        try:
            with self._connection() as connection:
                connection.execute("DELETE FROM events")
                connection.execute("DELETE FROM sessions")
                for path, events in sessions:
                    for event in events:
                        self._index_event(connection, event, path.name)
        except sqlite3.IntegrityError as error:
            self._schema_error(error)
        except sqlite3.Error as error:
            self._storage_error("Reconstruir el índice", error)
        return {
            "sessions": len(sessions),
            "events": sum(len(events) for _, events in sessions),
        }

    def delete_sessions(self, session_ids: list[str]) -> None:
        if not session_ids or not self.database_path.exists():
            return
        try:
            with self._connection() as connection:
                connection.executemany(
                    "DELETE FROM sessions WHERE session_id = ?",
                    ((session_id,) for session_id in session_ids),
                )
        except sqlite3.Error as error:
            self._storage_error("Actualizar la retención", error)

    def status(self) -> dict[str, object]:
        result: dict[str, object] = {
            "database_exists": self.database_path.exists(),
            "indexed_sessions": 0,
            "indexed_events": 0,
            "fts5": False,
        }
        if not self.database_path.exists():
            return result
        try:
            with self._connection() as connection:
                sessions = connection.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()
                events = connection.execute("SELECT COUNT(*) FROM events").fetchone()
                result["indexed_sessions"] = int(sessions[0]) if sessions else 0
                result["indexed_events"] = int(events[0]) if events else 0
                connection.execute("SELECT rowid FROM events_fts LIMIT 1").fetchone()
                result["fts5"] = True
        except sqlite3.Error as error:
            self._schema_error(error)
        return result

    def list_sessions(self, limit: int | None) -> list[dict[str, object]]:
        if not self.database_path.exists():
            return []
        query = """
            SELECT session_id, started_at_utc, ended_at_utc, status, file_name,
                   execution_mode, event_count, last_sequence
            FROM sessions
            ORDER BY started_at_utc DESC
        """
        parameters: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        try:
            with self._connection() as connection:
                return [dict(row) for row in connection.execute(query, parameters)]
        except sqlite3.Error as error:
            self._schema_error(error)

    def search(
        self,
        text: str,
        limit: int | None,
    ) -> list[dict[str, object]]:
        expression = self._search_expression(text)
        if not expression or not self.database_path.exists():
            return []
        query = """
            SELECT e.*
            FROM events_fts
            JOIN events AS e ON e.rowid = events_fts.rowid
            WHERE events_fts MATCH ?
            ORDER BY bm25(events_fts), e.occurred_at_utc,
                     e.session_id, e.sequence
        """
        parameters: list[object] = [expression]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        try:
            with self._connection() as connection:
                return [
                    self._event_row_to_dict(row)
                    for row in connection.execute(query, parameters)
                ]
        except sqlite3.Error as error:
            self._schema_error(error)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.database_path,
                timeout=BUSY_TIMEOUT_MILLISECONDS / 1000,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MILLISECONDS}")
            connection.execute("PRAGMA foreign_keys = ON")
            journal_mode = connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            if not journal_mode or str(journal_mode[0]).casefold() != "wal":
                connection.close()
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
                    detail="SQLite no pudo activar journal_mode WAL.",
                )
            connection.execute("PRAGMA synchronous = FULL")
            version_row = connection.execute("PRAGMA user_version").fetchone()
            version = int(version_row[0]) if version_row else 0
            if version not in (0, DATABASE_SCHEMA_VERSION):
                connection.close()
                raise NoxErrorFactory.create(
                    ErrorCode.AUDIT_SCHEMA_INVALID,
                    detail=f"Versión SQLite no compatible: {version}.",
                )
            connection.executescript(_SCHEMA)
            if version == 0:
                connection.execute(
                    f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}"
                )
                connection.commit()
            return connection
        except OSError as error:
            self._storage_error("Abrir el índice", error)

    @staticmethod
    def _index_event(
        connection: sqlite3.Connection,
        event: AuditEvent,
        file_name: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO sessions (
                session_id, started_at_utc, status, file_name, execution_mode
            ) VALUES (?, ?, 'active', ?, ?)
            """,
            (
                event.session_id,
                event.occurred_at_utc,
                file_name,
                event.execution_mode,
            ),
        )
        session = connection.execute(
            """
            SELECT file_name, execution_mode
            FROM sessions
            WHERE session_id = ?
            """,
            (event.session_id,),
        ).fetchone()
        if (
            session is None
            or session["file_name"] != file_name
            or session["execution_mode"] != event.execution_mode
        ):
            raise sqlite3.IntegrityError(
                f"Metadatos inconsistentes para {event.session_id}."
            )
        cursor = connection.execute(
            """
            INSERT INTO events (
                event_id, session_id, sequence, category, event_type,
                occurred_at_utc, interaction_id, operation_id, parent_event_id,
                execution_mode, duration_ms, data_json, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.session_id,
                event.sequence,
                event.category,
                event.event_type,
                event.occurred_at_utc,
                event.interaction_id,
                event.operation_id,
                event.parent_event_id,
                event.execution_mode,
                event.duration_ms,
                json.dumps(event.data, ensure_ascii=False, separators=(",", ":")),
                AuditIndex._searchable_text(event),
            ),
        )
        if cursor.rowcount:
            connection.execute(
                """
                UPDATE sessions
                SET event_count = event_count + 1,
                    last_sequence = MAX(last_sequence, ?)
                WHERE session_id = ?
                """,
                (event.sequence, event.session_id),
            )
        if event.event_type == "session.started":
            connection.execute(
                "UPDATE sessions SET started_at_utc = ?, status = 'active' "
                "WHERE session_id = ?",
                (event.occurred_at_utc, event.session_id),
            )
        elif event.event_type == "session.ended":
            connection.execute(
                "UPDATE sessions SET ended_at_utc = ?, status = 'closed' "
                "WHERE session_id = ?",
                (event.occurred_at_utc, event.session_id),
            )

    @staticmethod
    def _event_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_id": row["event_id"],
            "sequence": row["sequence"],
            "category": row["category"],
            "event_type": row["event_type"],
            "occurred_at_utc": row["occurred_at_utc"],
            "session_id": row["session_id"],
            "interaction_id": row["interaction_id"],
            "operation_id": row["operation_id"],
            "parent_event_id": row["parent_event_id"],
            "execution_mode": row["execution_mode"],
            "duration_ms": row["duration_ms"],
            "data": json.loads(row["data_json"]),
        }

    @staticmethod
    def _searchable_text(event: AuditEvent) -> str:
        return " ".join(
            (
                event.category,
                event.event_type,
                json.dumps(event.data, ensure_ascii=False, sort_keys=True),
            )
        )

    @staticmethod
    def _search_expression(text: str) -> str:
        tokens = re.findall(r"\w+", text, flags=re.UNICODE)
        return " OR ".join(f'"{token}"' for token in tokens)

    def _storage_error(
        self,
        operation: str,
        error: BaseException,
    ) -> NoReturn:
        raise NoxErrorFactory.create(
            ErrorCode.AUDIT_STORAGE_UNAVAILABLE,
            detail=f"{operation} en {self.database_path}: {error}",
        ) from error

    def _schema_error(self, error: BaseException) -> NoReturn:
        raise NoxErrorFactory.create(
            ErrorCode.AUDIT_SCHEMA_INVALID,
            detail=f"Índice inválido {self.database_path}: {error}",
        ) from error
