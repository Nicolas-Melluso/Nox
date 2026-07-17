"""Punto de entrada de la interfaz de línea de comandos de Nox."""

import argparse
import sys
from pathlib import Path

from nox_agent import __version__  # type: ignore
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.logs import NoxLogs
from nox_agent.project import InitResult, initialize_project
from nox_agent.registry import context_role, register_context

logger = NoxLogs.get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nox",
        description="Nox Agent",
    )
    parser.add_argument(
        "--version",
        "--v",
        "-version",
        "-v",
        action="version",
        version=f"Nox {__version__}",
        help="Muestra la versión instalada y termina.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "init",
        help="Inicializa Nox en el directorio actual.",
        description="Crea y valida la configuración local de Nox.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command is None:
        parser.print_help()
        return 0

    try:
        if arguments.command == "init":
            return _run_init()
    except NoxError as error:
        print(error.format_for_cli(), file=sys.stderr)
        return 1
    except Exception as error:  # Protección final para errores aún no mapeados.
        logger.exception("Error crítico no identificado")
        critical_error = NoxErrorFactory.create(
            ErrorCode.UNKNOWN_CRITICAL,
            detail=f"{type(error).__name__}: {error}",
        )
        print(critical_error.format_for_cli(), file=sys.stderr)
        return 2

    return 0


def _run_init() -> int:
    logger.debug("Inicializando proyecto en %s", Path.cwd())
    result = initialize_project(Path.cwd(), nox_version=__version__)
    registry = register_context(result.context)
    role = context_role(result.context, registry)
    _print_init_result(result, role=role)
    return 0


def _print_init_result(result: InitResult, *, role: str) -> None:
    context = result.context
    if result.created:
        print("Nox inicializó el proyecto correctamente.")
    else:
        print("Este proyecto ya estaba inicializado y es válido.")

    print()
    print(f"Proyecto: {context.manifest.name}")
    print(f"Raíz: {context.root}")
    print(f"Configuración: {context.root / '.nox' / 'project.toml'}")
    print(f"Contexto Nox: {role}")
    if context.parent is not None:
        print(f"Proyecto padre: {context.parent.manifest.name}")
        print(f"Raíz del padre: {context.parent.root}")
    print("Estado: saludable")
    print(f".gitignore: {result.gitignore_status}")


if __name__ == "__main__":
    raise SystemExit(main())
