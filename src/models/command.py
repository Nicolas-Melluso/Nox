"""Comandos del CLI para administrar modelos sin acoplarse a un proveedor."""

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from nox_agent.config import ConfigScope, ConfigurationManager
from nox_agent.config.model_menu import ModelConfigurationMenu
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import InstalledModel, ProviderFactory, ProviderIntegration
from nox_agent.models.manager import ModelManager, format_model_size
from nox_agent.tools import Confirmation, ConsoleMenu

JsonEmitter = Callable[[str, object], None]


def configure_models_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "models",
        help="Administra los modelos usados por Nox.",
    )
    commands = parser.add_subparsers(dest="models_command")
    commands.add_parser("list", help="Lista los modelos instalados.")
    commands.add_parser("actual", help="Muestra el modelo seleccionado por Nox.")
    install = commands.add_parser("install", help="Descarga un modelo.")
    install.add_argument("model")
    install.add_argument("--yes", action="store_true")
    use = commands.add_parser("use", help="Selecciona un modelo instalado.")
    use.add_argument("model")
    use.add_argument("--scope", choices=[scope.value for scope in ConfigScope], required=True)
    remove = commands.add_parser("remove", help="Elimina un modelo.")
    remove.add_argument("model")
    remove.add_argument("--yes", action="store_true")


def run_models(
    arguments: argparse.Namespace,
    *,
    start: Path,
    emit_json: JsonEmitter,
) -> int:
    configuration = ConfigurationManager(start)
    actual = configuration.effective()
    command = arguments.models_command

    if (
        command is None
        and not arguments.json
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        ModelConfigurationMenu(configuration, ConsoleMenu()).run()
        return 0
    if command == "actual":
        data = {
            "provider": actual.values["models.provider"].to_dict(),
            "model": actual.values["models.model"].to_dict(),
        }
        return _output("models.actual", data, arguments.json, emit_json)

    integration = ProviderFactory.integration(actual)
    integration.require_engine()
    models = integration.create_manager()
    available = _list_models(
        integration,
        models,
        allow_recovery=(
            not arguments.json
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        ),
    )
    if available is None:
        return 0

    if command is None or command == "list":
        installed = [model.to_dict() for model in available]
        return _output(
            "models.list",
            {"provider": integration.name, "models": installed},
            arguments.json,
            emit_json,
        )
    if command == "install":
        existing = models.find(arguments.model, available)
        if existing is not None:
            return _output(
                "models.install",
                {
                    "provider": integration.name,
                    "model": existing.name,
                    "installed": True,
                    "already_installed": True,
                },
                arguments.json,
                emit_json,
            )
        Confirmation.require(
            arguments.yes,
            f"Descargar el modelo {arguments.model}",
            allow_prompt=not arguments.json,
        )
        models.pull(
            arguments.model,
            on_progress=None if arguments.json else _progress,
        )
        installed = models.find(arguments.model)
        if installed is None:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_DOWNLOAD_FAILED,
                detail=f"No se encontró {arguments.model} después de la descarga.",
            )
        return _output(
            "models.install",
            {
                "provider": integration.name,
                "model": installed.name,
                "installed": True,
                "already_installed": False,
            },
            arguments.json,
            emit_json,
        )
    if command == "use":
        installed = models.find(arguments.model, available)
        if installed is None:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_FOUND,
                detail=f"Descargalo con: nox models install {arguments.model}",
            )
        scope = ConfigScope(arguments.scope)
        saved = configuration.set_many(
            {
                "models.provider": integration.name,
                "models.model": installed.name,
            },
            scope,
        )
        return _output(
            "models.use",
            {
                "model": saved["models.model"],
                "provider": saved["models.provider"],
                "scope": scope.value,
                "path": str(configuration.path_for_scope(scope)),
            },
            arguments.json,
            emit_json,
        )
    if command == "remove":
        installed = models.find(arguments.model, available)
        if installed is None:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_FOUND,
                detail=f"Modelo: {arguments.model}",
            )
        Confirmation.require(
            arguments.yes,
            f"Eliminar el modelo {installed.name}",
            allow_prompt=not arguments.json,
        )
        models.remove(installed.name)
        cleared_scopes = _clear_model_references(
            configuration,
            models,
            installed.name,
        )
        return _output(
            "models.remove",
            {
                "provider": integration.name,
                "model": installed.name,
                "removed": True,
                "cleared_scopes": cleared_scopes,
            },
            arguments.json,
            emit_json,
        )
    return 0


def _list_models(
    integration: ProviderIntegration,
    manager: ModelManager,
    *,
    allow_recovery: bool,
) -> list[InstalledModel] | None:
    try:
        return manager.list()
    except NoxError as error:
        if (
            error.code != ErrorCode.MODEL_PROVIDER_UNAVAILABLE
            or not allow_recovery
        ):
            raise
        if integration.recover_service(ConsoleMenu(), manager):
            return manager.list()
        return None


def _clear_model_references(
    configuration: ConfigurationManager,
    models: ModelManager,
    removed: str,
) -> list[str]:
    scopes = [ConfigScope.GLOBAL]
    if configuration.project is not None:
        scopes.append(ConfigScope.LOCAL)

    cleared: list[str] = []
    for scope in scopes:
        selected = configuration.values_for_scope(scope).get("models.model")
        if selected and models.matches(selected, removed):
            configuration.unset("models.model", scope)
            cleared.append(scope.value)
    return cleared


def _output(
    command: str,
    data: Mapping[str, object],
    output_json: bool,
    emit_json: JsonEmitter,
) -> int:
    if output_json:
        emit_json(command, data)
        return 0
    if command == "models.list":
        installed = data.get("models")
        if not isinstance(installed, list):
            return 0
        if not installed:
            print("No hay modelos instalados.")
        else:
            print("Modelos instalados\n")
            for model in installed:
                if not isinstance(model, dict):
                    continue
                print(f"{model.get('name')}  {format_model_size(model.get('size'))}")
    elif command == "models.actual":
        provider = data.get("provider")
        model = data.get("model")
        if not isinstance(provider, dict) or not isinstance(model, dict):
            return 0
        print(f"Proveedor: {provider.get('value')}")
        print(f"Modelo: {model.get('value') or '(sin definir)'}")
        print(f"Origen: {model.get('source')}")
    elif command == "models.install":
        if data.get("already_installed") is True:
            print(f"El modelo ya estaba instalado: {data['model']}")
        else:
            print(f"Modelo descargado: {data['model']}")
    elif command == "models.use":
        print(f"Modelo seleccionado: {data['model']}")
        print(f"Ámbito: {data['scope']}")
        print(f"Archivo: {data['path']}")
    else:
        print(f"Modelo eliminado: {data['model']}")
        cleared = data.get("cleared_scopes")
        if isinstance(cleared, list) and cleared:
            print(f"Selección limpiada en: {', '.join(str(item) for item in cleared)}")
    return 0


def _progress(status: str, completed: int | None, total: int | None) -> None:
    if completed is not None and total:
        percent = min(100, int(completed * 100 / total))
        print(f"\r{status}: {percent:3d}%", end="", flush=True)
        if completed >= total:
            print()
    else:
        print(f"\r{status}", end="", flush=True)
