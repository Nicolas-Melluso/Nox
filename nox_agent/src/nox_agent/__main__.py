"""Punto de entrada de la interfaz de línea de comandos de Nox."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nox_agent import __version__  # type: ignore
from nox_agent.config import ConfigurationManager
from nox_agent.config.command import configure_config_parser, run_config
from nox_agent.config.menu import ConfigurationMenu
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.engines.command import configure_engines_parser, run_engines
from nox_agent.logs import LogLevel, NoxLogs
from nox_agent.models.command import configure_models_parser, run_models
from nox_agent.models.setup import LocalIntelligenceSetup
from nox_agent.project import InitResult, initialize_project
from nox_agent.registry import context_role, register_context
from nox_agent.runtime import ReplSession, StatusService
from nox_agent.tools import ConsoleMenu, MenuItem

logger = NoxLogs.get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nox", description="Nox Agent")
    parser.add_argument(
        "--version",
        "--v",
        "-version",
        "-v",
        dest="show_version",
        action="store_true",
        help="Muestra la versión instalada y termina.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Devuelve una respuesta estructurada para automatizaciones.",
    )
    parser.add_argument(
        "--status",
        dest="show_status",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "init",
        help="Inicializa Nox en el directorio actual.",
        description="Crea y valida la configuración local de Nox.",
    )
    subparsers.add_parser(
        "start",
        help="Inicia una sesión conversacional con Nox.",
        description="Abre el REPL de Nox dentro del proyecto actual.",
    )
    configure_config_parser(subparsers)
    configure_engines_parser(subparsers)
    configure_models_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    normalized = _normalize_argv(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    arguments = parser.parse_args(normalized)

    if arguments.show_version:
        if arguments.json:
            _print_json("version", {"version": __version__})
        else:
            print(f"Nox {__version__}")
        return 0
    if arguments.show_status:
        try:
            _print_status()
        except NoxError as error:
            _print_json("status", None, error=error)
            return 1
        except Exception as error:
            critical = NoxErrorFactory.create(
                ErrorCode.UNKNOWN_CRITICAL,
                detail=f"{type(error).__name__}: {error}",
            )
            _print_json("status", None, error=critical)
            return 2
        return 0
    if arguments.command is None and (
        arguments.json
        or not sys.stdin.isatty()
        or not sys.stdout.isatty()
    ):
        parser.print_help()
        return 0
    try:
        _configure_effective_logs(Path.cwd())
        if arguments.command is None:
            return _run_home()
        if arguments.command == "init":
            return _run_init(output_json=arguments.json)
        if arguments.command == "config":
            return run_config(
                arguments,
                start=Path.cwd(),
                emit_json=_print_json,
            )
        if arguments.command == "start":
            if arguments.json:
                raise NoxErrorFactory.create(
                    ErrorCode.CONFIG_INVALID,
                    detail="nox start es interactivo y no admite --json.",
                )
            return ReplSession(Path.cwd(), nox_version=__version__).run()
        if arguments.command == "engines":
            return run_engines(arguments, emit_json=_print_json)
        if arguments.command == "models":
            return run_models(
                arguments,
                start=Path.cwd(),
                emit_json=_print_json,
            )
    except KeyboardInterrupt:
        cancelled = NoxErrorFactory.create(ErrorCode.OPERATION_CANCELLED)
        if arguments.json:
            _print_json(_command_identifier(arguments), None, error=cancelled)
        else:
            print(f"\n{cancelled.format_for_cli()}", file=sys.stderr)
        return 130
    except NoxError as error:
        if arguments.json:
            _print_json(_command_identifier(arguments), None, error=error)
        else:
            print(error.format_for_cli(), file=sys.stderr)
        return 1
    except Exception as error:  # Protección final para errores aún no mapeados.
        logger.exception("Error crítico no identificado")
        critical = NoxErrorFactory.create(
            ErrorCode.UNKNOWN_CRITICAL,
            detail=f"{type(error).__name__}: {error}",
        )
        if arguments.json:
            _print_json(_command_identifier(arguments), None, error=critical)
        else:
            print(critical.format_for_cli(), file=sys.stderr)
        return 2
    return 0


def _run_home() -> int:
    menu = ConsoleMenu()
    while True:
        selected = menu.select(
            "Nox",
            [
                MenuItem("Iniciar Nox", "start"),
                MenuItem("Preparar inteligencia local", "prepare"),
                MenuItem("Configuración", "config"),
                MenuItem("Ayuda", "help"),
                MenuItem("Salir", "exit"),
            ],
            description=f"Nox {__version__}",
        )
        if selected is None or selected.value == "exit":
            menu.clear()
            return 0
        if selected.value == "start":
            return ReplSession(Path.cwd(), nox_version=__version__).run()
        if selected.value == "prepare":
            manager = ConfigurationManager(Path.cwd())
            if LocalIntelligenceSetup(manager, menu).ensure_ready():
                values = manager.effective().values
                menu.message(
                    "Inteligencia local preparada",
                    [
                        f"Proveedor: {values['models.provider'].value}",
                        f"Modelo: {values['models.model'].value}",
                    ],
                )
        elif selected.value == "config":
            ConfigurationMenu(Path.cwd()).run()
        elif selected.value == "help":
            menu.message(
                "Comandos principales",
                [
                    "nox start · Iniciar una conversación",
                    "nox init · Inicializar el proyecto actual",
                    "nox models · Preparar y administrar modelos",
                    "nox --config · Configurar Nox",
                    "nox --help · Ver toda la ayuda técnica",
                ],
            )


def _run_init(*, output_json: bool) -> int:
    logger.debug("Inicializando proyecto en %s", Path.cwd())
    result = initialize_project(Path.cwd(), nox_version=__version__)
    registry = register_context(result.context)
    role = context_role(result.context, registry)
    if output_json:
        _print_json("init", _init_result_as_dict(result, role=role))
    else:
        _print_init_result(result, role=role)
    return 0


def _configure_effective_logs(start: Path) -> None:
    configuration = ConfigurationManager(start).effective()
    NoxLogs.configure(LogLevel(configuration.values["logs.level"].value))


def _print_status() -> None:
    status = StatusService.collect(Path.cwd(), nox_version=__version__)
    _print_json("status", status)


def _init_result_as_dict(result: InitResult, *, role: str) -> dict[str, object]:
    context = result.context
    parent = None
    if context.parent is not None:
        parent = {
            "id": context.parent.manifest.project_id,
            "name": context.parent.manifest.name,
            "root": str(context.parent.root),
        }
    return {
        "created": result.created,
        "project": {
            "id": context.manifest.project_id,
            "name": context.manifest.name,
            "root": str(context.root),
            "manifest": str(context.root / ".nox" / "project.toml"),
            "role": role.lower(),
            "parent": parent,
        },
        "health": "healthy",
        "gitignore": result.gitignore_status,
    }


def _print_init_result(result: InitResult, *, role: str) -> None:
    context = result.context
    message = (
        "Nox inicializó el proyecto correctamente."
        if result.created
        else "Este proyecto ya estaba inicializado y es válido."
    )
    print(message)
    print(f"\nProyecto: {context.manifest.name}")
    print(f"Raíz: {context.root}")
    print(f"Configuración: {context.root / '.nox' / 'project.toml'}")
    print(f"Contexto Nox: {role}")
    if context.parent is not None:
        print(f"Proyecto padre: {context.parent.manifest.name}")
        print(f"Raíz del padre: {context.parent.root}")
    print("Estado: saludable")
    print(f".gitignore: {result.gitignore_status}")


def _print_json(
    command: str | None,
    data: object,
    *,
    error: NoxError | None = None,
) -> None:
    payload = {
        "ok": error is None,
        "command": command,
        "data": data if error is None else None,
        "error": error.to_dict() if error is not None else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _normalize_argv(argv: list[str]) -> list[str]:
    normalized = ["config" if value == "--config" else value for value in argv]
    if "--json" in normalized:
        normalized = [value for value in normalized if value != "--json"]
        normalized.insert(0, "--json")
    return normalized


def _command_identifier(arguments: argparse.Namespace) -> str | None:
    if arguments.command == "config" and arguments.config_command:
        return f"config.{arguments.config_command}"
    if arguments.command == "engines" and arguments.engines_command:
        return f"engines.{arguments.engines_command}"
    if arguments.command == "models" and arguments.models_command:
        return f"models.{arguments.models_command}"
    return arguments.command


if __name__ == "__main__":
    raise SystemExit(main())
