"""Comandos directos para consultar y modificar feature flags."""

import argparse
from collections.abc import Callable
from pathlib import Path

from nox_agent.config import ConfigScope
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.feature_flags.catalog import FeatureFlagCatalog
from nox_agent.feature_flags.manager import (
    EffectiveFeatureFlagValue,
    FeatureFlagManager,
)

JsonEmitter = Callable[[str, object], None]


def configure_flags_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "flags",
        help="Consulta o modifica los feature flags de Nox.",
    )
    commands = parser.add_subparsers(dest="flags_command")
    commands.add_parser("list", help="Lista los feature flags disponibles.")
    commands.add_parser(
        "actual",
        help="Muestra los valores actuales y su origen.",
    )

    get_parser = commands.add_parser(
        "get",
        help="Muestra un feature flag y su origen.",
    )
    get_parser.add_argument("key")

    set_parser = commands.add_parser(
        "set",
        help="Guarda un override global o local.",
    )
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in ConfigScope],
        required=True,
    )

    unset_parser = commands.add_parser(
        "unset",
        help="Elimina un override y recupera la precedencia anterior.",
    )
    unset_parser.add_argument("key")
    unset_parser.add_argument(
        "--scope",
        choices=[scope.value for scope in ConfigScope],
        required=True,
    )


def run_flags(
    arguments: argparse.Namespace,
    *,
    start: Path,
    emit_json: JsonEmitter,
) -> int:
    manager = FeatureFlagManager(start)
    command = arguments.flags_command

    if command == "list":
        definitions = [
            definition.to_dict(default=manager.defaults[definition.key])
            for definition in FeatureFlagCatalog.DEFINITIONS
        ]
        return _output(
            "flags.list",
            {
                "environment": manager.environment,
                "flags": definitions,
            },
            arguments.json,
            emit_json,
        )

    if command is None or command == "actual":
        return _output(
            "flags.actual",
            manager.effective().to_dict(),
            arguments.json,
            emit_json,
        )

    if command == "get":
        FeatureFlagCatalog.definition(arguments.key)
        current = manager.effective().values[arguments.key]
        return _output(
            "flags.get",
            {
                "key": arguments.key,
                **current.to_dict(),
            },
            arguments.json,
            emit_json,
        )

    scope = _parse_scope(arguments.scope)
    if command == "set":
        definition = FeatureFlagCatalog.definition(arguments.key)
        value = definition.parse_cli(arguments.value)
        manager.set(arguments.key, value, scope)
        current = manager.effective().values[arguments.key]
        return _output(
            "flags.set",
            {
                "key": arguments.key,
                "scope": scope.value,
                "saved_path": str(manager.path_for_scope(scope)),
                **current.to_dict(),
            },
            arguments.json,
            emit_json,
        )

    if command == "unset":
        removed = manager.unset(arguments.key, scope)
        current = manager.effective().values[arguments.key]
        return _output(
            "flags.unset",
            {
                "key": arguments.key,
                "scope": scope.value,
                "removed": removed is not None,
                "removed_value": removed,
                "saved_path": str(manager.path_for_scope(scope)),
                **current.to_dict(),
            },
            arguments.json,
            emit_json,
        )
    return 0


def _parse_scope(value: str) -> ConfigScope:
    try:
        return ConfigScope(value)
    except ValueError as error:
        raise NoxErrorFactory.create(
            ErrorCode.CONFIG_VALUE_INVALID,
            detail=f"Ámbito desconocido: {value}",
        ) from error


def _output(
    command: str,
    data: dict[str, object],
    output_json: bool,
    emit_json: JsonEmitter,
) -> int:
    if output_json:
        emit_json(command, data)
        return 0

    if command == "flags.list":
        print("Feature flags disponibles\n")
        definitions = data.get("flags")
        if isinstance(definitions, list):
            for item in definitions:
                if not isinstance(item, dict):
                    continue
                print(f"{item.get('key')} ({item.get('kind')})")
                print(f"  Default: {_render_value(item.get('default'))}")
                print(f"  {item.get('description')}")
        return 0

    if command == "flags.actual":
        print(f"Entorno: {data.get('environment')}\n")
        values = data.get("values")
        if isinstance(values, dict):
            for key, raw_value in values.items():
                if not isinstance(raw_value, dict):
                    continue
                print(
                    f"{key} = {_render_value(raw_value.get('value'))} "
                    f"({raw_value.get('source')})"
                )
        return 0

    _print_value(str(data["key"]), data)
    if command == "flags.set":
        print(f"Guardado en: {data['saved_path']}")
    elif command == "flags.unset":
        if data["removed"] is True:
            print(f"Override eliminado de: {data['saved_path']}")
        else:
            print("No había un override guardado en ese ámbito.")
    return 0


def _print_value(
    key: str,
    value: dict[str, object] | EffectiveFeatureFlagValue,
) -> None:
    data = value.to_dict() if isinstance(value, EffectiveFeatureFlagValue) else value
    print(f"{key} = {_render_value(data.get('value'))}")
    print(f"Origen: {data.get('source')}")
    print(f"Default: {_render_value(data.get('default'))}")
    print(f"Global: {_render_optional(data.get('global'))}")
    print(f"Local: {_render_optional(data.get('local'))}")


def _render_optional(value: object) -> str:
    return "(sin definir)" if value is None else _render_value(value)


def _render_value(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)
