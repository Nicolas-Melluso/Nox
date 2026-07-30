"""Comandos del CLI para administrar motores locales."""

import argparse
from collections.abc import Callable, Mapping

from nox_agent.engines import OllamaEngine
from nox_agent.tools import Confirmation

JsonEmitter = Callable[[str, object], None]


def configure_engines_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "engines",
        help="Administra motores locales de inteligencia.",
    )
    commands = parser.add_subparsers(dest="engines_command")
    commands.add_parser("status", help="Muestra el estado de los motores.")
    versions = commands.add_parser(
        "versions",
        help="Consulta versiones oficiales disponibles.",
    )
    versions.add_argument("engine", choices=["ollama"])
    versions.add_argument("--limit", type=int, default=10)
    versions.add_argument("--prerelease", action="store_true")
    install = commands.add_parser(
        "install",
        help="Descarga e instala un motor desde su fuente oficial.",
    )
    install.add_argument("engine", choices=["ollama"])
    install.add_argument("--version", default="latest")
    install.add_argument("--yes", action="store_true")


def run_engines(
    arguments: argparse.Namespace,
    *,
    emit_json: JsonEmitter,
) -> int:
    command = arguments.engines_command
    if command is None or command == "status":
        data = {"engines": [OllamaEngine.status()]}
        _output("engines.status", data, arguments.json, emit_json)
        return 0
    if command == "versions":
        limit = max(1, min(arguments.limit, 30))
        releases = OllamaEngine.releases(
            include_prerelease=arguments.prerelease,
        )[:limit]
        data = {"engine": "ollama", "versions": [item.to_dict() for item in releases]}
        _output("engines.versions", data, arguments.json, emit_json)
        return 0
    if command == "install":
        Confirmation.require(
            arguments.yes,
            f"Descargar e instalar Ollama {arguments.version} desde la fuente oficial",
            allow_prompt=not arguments.json,
        )
        data = OllamaEngine.install(
            arguments.version,
            on_progress=None if arguments.json else _print_progress,
        )
        _output("engines.install", data, arguments.json, emit_json)
        return 0
    return 0


def _output(
    command: str,
    data: Mapping[str, object],
    output_json: bool,
    emit_json: JsonEmitter,
) -> None:
    if output_json:
        emit_json(command, data)
        return
    if command == "engines.status":
        engines = data.get("engines")
        if not isinstance(engines, list) or not engines:
            return
        engine = engines[0]
        if not isinstance(engine, dict):
            return
        installed = engine.get("installed") is True
        print(f"Ollama: {'instalado' if installed else 'no instalado'}")
        if installed:
            print(f"Versión: {engine.get('version') or '(desconocida)'}")
            print(f"Ejecutable: {engine.get('executable')}")
        else:
            print("Siguiente paso: ejecutá `nox models` y elegí "
                  "‘Preparar inteligencia local’.")
    elif command == "engines.versions":
        print("Versiones oficiales de Ollama\n")
        versions = data.get("versions")
        if not isinstance(versions, list):
            return
        for release in versions:
            if not isinstance(release, dict):
                continue
            suffix = " (pre-release)" if release.get("prerelease") is True else ""
            print(f"{release.get('version')}{suffix}")
    else:
        print("Ollama se instaló correctamente.")
        print(f"Versión detectada: {data['version'] or '(desconocida)'}")
        print(f"Ejecutable: {data['executable']}")


def _print_progress(downloaded: int, total: int | None) -> None:
    if total:
        percent = min(100, int(downloaded * 100 / total))
        print(f"\rDescargando Ollama: {percent:3d}%", end="", flush=True)
        if downloaded >= total:
            print()
    else:
        mebibytes = downloaded / (1024 * 1024)
        print(f"\rDescargando Ollama: {mebibytes:.1f} MiB", end="", flush=True)
