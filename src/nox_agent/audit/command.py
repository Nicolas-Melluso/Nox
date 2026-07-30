"""Comandos del CLI para consultar y administrar la auditoría."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from nox_agent.audit.query import AuditQueryService, NO_MATCHES_MESSAGE
from nox_agent.audit.store import AuditStore
from nox_agent.config import ConfigurationManager
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.feature_flags import FeatureFlagManager
from nox_agent.models import ProviderFactory
from nox_agent.tools import Confirmation

DEFAULT_LIST_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 0

JsonEmitter = Callable[[str, object], None]


def configure_audit_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "audit",
        help="Consulta la auditoría persistente de Nox.",
    )
    commands = parser.add_subparsers(dest="audit_command")
    commands.add_parser("status", help="Muestra el estado de la auditoría.")

    list_command = commands.add_parser(
        "list",
        help="Lista las sesiones auditadas.",
    )
    list_command.add_argument("--limit", type=_non_negative_limit, default=DEFAULT_LIST_LIMIT)

    show = commands.add_parser(
        "show",
        help="Muestra todos los eventos de una sesión.",
    )
    show.add_argument("session")

    search = commands.add_parser(
        "search",
        help="Busca eventos en el índice de texto.",
    )
    search.add_argument("query", nargs="+")
    search.add_argument(
        "--limit",
        type=_non_negative_limit,
        default=DEFAULT_SEARCH_LIMIT,
        help="Máximo de coincidencias; 0 devuelve todas.",
    )

    ask = commands.add_parser(
        "ask",
        help="Responde una pregunta usando la auditoría como evidencia.",
    )
    ask.add_argument("question", nargs="+")

    clear = commands.add_parser(
        "clear",
        help="Elimina toda la auditoría persistente.",
    )
    clear.add_argument(
        "--all",
        action="store_true",
        required=True,
        help="Confirma que el alcance incluye todas las sesiones.",
    )
    clear.add_argument("--yes", action="store_true")


def run_audit(
    arguments: argparse.Namespace,
    *,
    start: Path,
    emit_json: JsonEmitter,
) -> int:
    store = AuditStore()
    command = arguments.audit_command
    retention_hours = _retention_hours(start)
    if command != "clear":
        store.cleanup(retention_hours)

    if command is None or command == "status":
        store.synchronize()
        status = store.status()
        status["retention_hours"] = retention_hours
        return _output(
            "audit.status",
            status,
            arguments.json,
            emit_json,
        )
    if command == "list":
        store.synchronize()
        sessions = store.list_sessions(_optional_limit(arguments.limit))
        return _output(
            "audit.list",
            {
                "limit": arguments.limit,
                "count": len(sessions),
                "sessions": sessions,
            },
            arguments.json,
            emit_json,
        )
    if command == "show":
        events = store.read_session(arguments.session)
        if not events:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_SESSION_NOT_FOUND,
                detail=f"Sesión: {arguments.session}",
            )
        return _output(
            "audit.show",
            {
                "session_id": arguments.session,
                "event_count": len(events),
                "events": events,
            },
            arguments.json,
            emit_json,
        )
    if command == "search":
        store.synchronize()
        query = " ".join(arguments.query).strip()
        if not query:
            raise NoxErrorFactory.create(
                ErrorCode.AUDIT_QUERY_INVALID,
                detail="La búsqueda no puede estar vacía.",
            )
        events = store.search(query, _optional_limit(arguments.limit))
        return _output(
            "audit.search",
            {
                "query": query,
                "limit": arguments.limit,
                "count": len(events),
                "events": events,
            },
            arguments.json,
            emit_json,
        )
    if command == "ask":
        store.synchronize()
        question = " ".join(arguments.question).strip()
        configuration = ConfigurationManager(start).effective()
        provider = ProviderFactory.create(configuration)
        provider.prepare()
        result = AuditQueryService(store, provider).ask(question)
        return _output(
            "audit.ask",
            result.to_dict(),
            arguments.json,
            emit_json,
        )
    if command == "clear":
        Confirmation.require(
            arguments.yes,
            "Eliminar toda la auditoría persistente de Nox",
            allow_prompt=not arguments.json,
        )
        removed = store.clear_all()
        return _output(
            "audit.clear",
            {
                "cleared": True,
                "removed_sessions": removed,
            },
            arguments.json,
            emit_json,
        )
    return 0


def _output(
    command: str,
    data: Mapping[str, object],
    output_json: bool,
    emit_json: JsonEmitter,
) -> int:
    if output_json:
        emit_json(command, data)
        return 0

    if command == "audit.status":
        _print_status(data)
    elif command == "audit.list":
        _print_sessions(data)
    elif command == "audit.show":
        events = _events_from(data)
        print(f"Sesión: {data.get('session_id')}")
        print(f"Eventos: {len(events)}\n")
        _print_events(events)
    elif command == "audit.search":
        events = _events_from(data)
        if not events:
            print(NO_MATCHES_MESSAGE)
        else:
            print(f"Coincidencias: {len(events)}\n")
            _print_events(events)
    elif command == "audit.ask":
        answer = data.get("answer")
        events = _events_from(data)
        print(str(answer or NO_MATCHES_MESSAGE))
        if events:
            print(f"\nCoincidencias recuperadas: {len(events)}\n")
            _print_events(events)
            evidence = data.get("evidence")
            if isinstance(evidence, dict) and evidence.get("truncated") is True:
                print(
                    "\nLa evidencia enviada al modelo fue truncada; "
                    "las coincidencias anteriores están completas."
                )
    else:
        print(
            "Auditoría eliminada. "
            f"Sesiones borradas: {data.get('removed_sessions', 0)}"
        )
    return 0


def _print_status(data: Mapping[str, object]) -> None:
    print("Auditoría de Nox")
    print(f"Raíz: {data.get('root')}")
    print(f"Sesiones canónicas: {data.get('session_files', 0)}")
    print(f"Sesiones indexadas: {data.get('indexed_sessions', 0)}")
    print(f"Eventos indexados: {data.get('indexed_events', 0)}")
    print(f"Sesiones activas locales: {data.get('active_sessions', 0)}")
    print(f"Retención: {data.get('retention_hours')} horas")
    print(f"Índice FTS5: {'disponible' if data.get('fts5') is True else 'no creado'}")


def _print_sessions(data: Mapping[str, object]) -> None:
    sessions = data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        print("No hay sesiones auditadas.")
        return
    print(f"Sesiones auditadas: {len(sessions)}\n")
    for index, session in enumerate(sessions, start=1):
        if not isinstance(session, dict):
            continue
        print(f"[{index}] {session.get('session_id')}")
        print(f"Inicio: {session.get('started_at_utc')}")
        print(f"Fin: {session.get('ended_at_utc') or '(sesión activa)'}")
        print(f"Estado: {session.get('status')}")
        print(f"Modo: {session.get('execution_mode')}")
        print(f"Eventos: {session.get('event_count', 0)}")
        if index != len(sessions):
            print()


def _print_events(events: list[dict[str, object]]) -> None:
    for index, event in enumerate(events, start=1):
        print(f"[{index}] {event.get('event_type')}")
        print(f"Evento: {event.get('event_id')}")
        print(f"Sesión: {event.get('session_id')}")
        print(f"Fecha UTC: {event.get('occurred_at_utc')}")
        print(f"Categoría: {event.get('category')}")
        print(f"Modo: {event.get('execution_mode')}")
        duration = event.get("duration_ms")
        if duration is not None:
            print(f"Duración: {duration} ms")
        print(
            "Datos: "
            + json.dumps(
                event.get("data", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if index != len(events):
            print()


def _events_from(data: Mapping[str, object]) -> list[dict[str, object]]:
    events = data.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _optional_limit(value: int) -> int | None:
    return None if value == 0 else value


def _retention_hours(start: Path) -> int:
    value = FeatureFlagManager(start).effective().get("audit.retention_hours")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NoxErrorFactory.create(
            ErrorCode.FEATURE_FLAGS_INVALID,
            detail="audit.retention_hours debe ser un entero no negativo.",
        )
    return value


def _non_negative_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit debe ser un entero.") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit debe ser mayor o igual a 0.")
    return parsed
