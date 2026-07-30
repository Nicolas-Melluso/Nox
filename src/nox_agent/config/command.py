"""Comandos directos del dominio de configuración."""

import argparse
from collections.abc import Callable
from pathlib import Path

from nox_agent.config.catalog import ConfigScope, ConfigurationCatalog
from nox_agent.config.manager import ConfigurationManager, EffectiveConfiguration
from nox_agent.config.menu import ConfigurationMenu
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.logs import LogLevel, NoxLogs
from nox_agent.models import ProviderFactory
from nox_agent.registry import register_context

JsonEmitter = Callable[[str, object], None]


def configure_config_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    config_parser = subparsers.add_parser(
        "config",
        help="Abre o consulta la configuración de Nox.",
    )
    commands = config_parser.add_subparsers(dest="config_command")
    commands.add_parser("list", help="Lista las secciones configurables.")
    commands.add_parser(
        "actual",
        help="Muestra la configuración actual y su origen.",
    )
    logs_parser = commands.add_parser(
        "logs",
        help="Consulta o modifica la configuración de logs.",
    )
    logs_parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=[level.value for level in LogLevel],
        help="Nivel de logs que se guardará.",
    )
    logs_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in ConfigScope],
        help="Ámbito que se consultará o modificará: global o local.",
    )
    models_parser = commands.add_parser(
        "models",
        help="Consulta o modifica el proveedor y modelo de Nox.",
    )
    models_parser.add_argument(
        "--provider",
        type=str.lower,
        choices=ProviderFactory.names(),
        help="Proveedor de inferencia.",
    )
    models_parser.add_argument("--model", help="Nombre exacto del modelo.")
    models_parser.add_argument(
        "--ollama-url",
        help="Dirección del servicio local de Ollama.",
    )
    models_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in ConfigScope],
        help="Ámbito que se consultará o modificará: global o local.",
    )


def run_config(
    arguments: argparse.Namespace,
    *,
    start: Path,
    emit_json: JsonEmitter,
) -> int:
    manager = ConfigurationManager(start)
    if manager.project is not None:
        register_context(manager.project)

    command = arguments.config_command
    if command is None:
        if arguments.json:
            return _print_sections(True, emit_json)
        ConfigurationMenu(start).run()
        return 0
    if command == "list":
        return _print_sections(arguments.json, emit_json)
    if command == "actual":
        _print_actual(manager.effective(), arguments.json, emit_json)
        return 0
    if command == "logs":
        return _run_logs(manager, arguments, emit_json)
    if command == "models":
        return _run_models(manager, arguments, emit_json)
    return 0


def _run_models(
    manager: ConfigurationManager,
    arguments: argparse.Namespace,
    emit_json: JsonEmitter,
) -> int:
    scope = ConfigScope(arguments.scope) if arguments.scope else None
    changes = {
        key: value
        for key, value in {
            "models.provider": arguments.provider,
            "models.model": arguments.model,
            "models.ollama_url": arguments.ollama_url,
        }.items()
        if value is not None
    }
    if changes and scope is None:
        raise NoxErrorFactory.create(
            ErrorCode.CONFIG_INVALID,
            detail="Para modificar models indicá --scope global o --scope local.",
        )

    saved_path: Path | None = None
    if changes and scope is not None:
        manager.set_many(changes, scope)
        saved_path = manager.path_for_scope(scope)

    configuration = manager.effective()
    keys = ("models.provider", "models.model", "models.ollama_url")
    data: dict[str, object] = {
        "values": {
            key: configuration.values[key].to_dict()
            for key in keys
        },
        "saved_path": str(saved_path) if saved_path else None,
    }
    if scope is not None:
        data["scope"] = scope.value

    if arguments.json:
        emit_json("config.models", data)
    else:
        if saved_path is not None:
            print("Configuración guardada.\n")
        for key in keys:
            value = configuration.values[key]
            shown = value.value or "(sin definir)"
            print(f"{key} = {shown}")
            print(f"  Origen: {value.source}")
        if saved_path is not None:
            print(f"Archivo: {saved_path}")
    return 0


def _run_logs(
    manager: ConfigurationManager,
    arguments: argparse.Namespace,
    emit_json: JsonEmitter,
) -> int:
    scope = ConfigScope(arguments.scope) if arguments.scope else None
    if arguments.log_level and scope is None:
        raise NoxErrorFactory.create(
            ErrorCode.CONFIG_INVALID,
            detail="Para modificar logs.level indicá --scope global o --scope local.",
        )

    saved_path: Path | None = None
    if arguments.log_level and scope is not None:
        value = manager.set("logs.level", arguments.log_level, scope)
        saved_path = manager.path_for_scope(scope)
        NoxLogs.set_level(LogLevel(value))

    effective = manager.effective().values["logs.level"]
    data: dict[str, object] = {
        "key": "logs.level",
        **effective.to_dict(),
        "saved_path": str(saved_path) if saved_path else None,
    }
    if scope is not None:
        data["scope"] = scope.value
        data["scope_value"] = manager.values_for_scope(scope).get("logs.level")

    if arguments.json:
        emit_json("config.logs", data)
    else:
        if saved_path is not None:
            print("Configuración guardada.\n")
        print(f"logs.level = {effective.value}")
        print(f"Origen: {effective.source}")
        print(f"General: {effective.global_value or '(sin definir)'}")
        print(f"Local: {effective.local_value or '(sin definir)'}")
        if saved_path is not None:
            print(f"Archivo: {saved_path}")
    return 0


def _print_sections(output_json: bool, emit_json: JsonEmitter) -> int:
    sections = ConfigurationCatalog.sections_as_dict()
    if output_json:
        emit_json("config.list", {"sections": sections})
        return 0
    print("Configuración de Nox\n")
    for section in sections:
        status = "Disponible" if section["status"] == "available" else "Próximamente"
        print(f"{section['title']}: {status}")
        print(f"  {section['description']}")
    return 0


def _print_actual(
    configuration: EffectiveConfiguration,
    output_json: bool,
    emit_json: JsonEmitter,
) -> None:
    if output_json:
        emit_json("config.actual", configuration.to_dict())
        return
    print("Configuración actual\n")
    for key, value in configuration.values.items():
        print(f"{key} = {value.value or '(sin definir)'}")
        print(f"  Origen: {value.source}")
        print(f"  General: {value.global_value or '(sin definir)'}")
        print(f"  Local: {value.local_value or '(sin definir)'}")
