"""Persistencia y resolución de la configuración de Nox."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from nox_agent.config.catalog import ConfigScope, ConfigurationCatalog
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.project import ProjectContext, find_active_project
from nox_agent.tools import FileManager

CONFIG_SCHEMA_VERSION = 1
CONFIG_FILENAME = "config.toml"


@dataclass(frozen=True)
class EffectiveConfigValue:
    key: str
    value: str
    source: str
    default_value: str
    global_value: str | None
    local_value: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "value": self.value,
            "source": self.source,
            "default": self.default_value,
            "global": self.global_value,
            "local": self.local_value,
        }


@dataclass(frozen=True)
class EffectiveConfiguration:
    values: dict[str, EffectiveConfigValue]
    project: ProjectContext | None

    def to_dict(self) -> dict[str, object]:
        project = None
        if self.project is not None:
            project = {
                "id": self.project.manifest.project_id,
                "name": self.project.manifest.name,
                "root": str(self.project.root),
            }
        return {
            "values": {key: value.to_dict() for key, value in self.values.items()},
            "project": project,
        }


class ConfigurationManager:
    """Lee, modifica y combina configuración general y local."""

    def __init__(self, start: Path) -> None:
        self.start = start.resolve()
        self.project = find_active_project(self.start)

    def effective(self) -> EffectiveConfiguration:
        global_values = self._read_path(self.global_path())
        local_values = self._read_path(self.local_path()) if self.project else {}
        values: dict[str, EffectiveConfigValue] = {}

        for key, option in ConfigurationCatalog.OPTIONS.items():
            global_value = global_values.get(key)
            local_value = local_values.get(key)
            value = local_value or global_value or option.default
            source = (
                ConfigScope.LOCAL.value
                if local_value is not None
                else ConfigScope.GLOBAL.value
                if global_value is not None
                else "default"
            )
            values[key] = EffectiveConfigValue(
                key=key,
                value=value,
                source=source,
                default_value=option.default,
                global_value=global_value,
                local_value=local_value,
            )
        return EffectiveConfiguration(values=values, project=self.project)

    def set(self, key: str, value: object, scope: ConfigScope) -> str:
        option = ConfigurationCatalog.option(key)
        if scope not in option.scopes:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"{key} no admite el ámbito {scope.value}.",
            )
        normalized = option.normalize(value)
        path = self.path_for_scope(scope)
        values = self._read_path(path)
        values[key] = normalized

        try:
            FileManager.atomic_write_text(
                path,
                self._render(values),
                create_parents=True,
            )
        except OSError as error:
            raise NoxErrorFactory.create(
                ErrorCode.FILESYSTEM_ERROR,
                detail=f"Escribir {path}: {error}",
            ) from error
        return normalized

    def values_for_scope(self, scope: ConfigScope) -> dict[str, str]:
        return self._read_path(self.path_for_scope(scope))

    def path_for_scope(self, scope: ConfigScope) -> Path:
        return self.global_path() if scope == ConfigScope.GLOBAL else self.local_path()

    @staticmethod
    def global_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail="Windows no informó la ubicación LOCALAPPDATA.",
            )
        return Path(local_app_data) / "Nox" / CONFIG_FILENAME

    def local_path(self) -> Path:
        if self.project is None:
            raise NoxErrorFactory.create(
                ErrorCode.LOCAL_PROJECT_REQUIRED,
                detail="Ejecutá nox init antes de guardar configuración local.",
            )
        return self.project.root / ".nox" / CONFIG_FILENAME

    @staticmethod
    def _read_path(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        if not path.is_file():
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"La ruta de configuración no es un archivo: {path}",
            )
        try:
            with path.open("rb") as config_file:
                data = tomllib.load(config_file)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"Leer {path}: {error}",
            ) from error

        ConfigurationManager._validate_document(data, path)
        values: dict[str, str] = {}
        logs = data.get("logs")
        if isinstance(logs, dict) and "level" in logs:
            option = ConfigurationCatalog.option("logs.level")
            values[option.key] = option.normalize(logs["level"])
        return values

    @staticmethod
    def _validate_document(data: dict[str, object], path: Path) -> None:
        if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=(
                    f"{path}: schema_version esperado {CONFIG_SCHEMA_VERSION}, "
                    f"recibido {data.get('schema_version')!r}."
                ),
            )
        unknown_sections = sorted(set(data) - {"schema_version", "logs"})
        if unknown_sections:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"Secciones desconocidas: {', '.join(unknown_sections)}",
            )
        logs = data.get("logs")
        if logs is None:
            return
        if not isinstance(logs, dict):
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail="La sección logs debe ser una tabla TOML.",
            )
        unknown_options = sorted(set(logs) - {"level"})
        if unknown_options:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"Opciones desconocidas en logs: {', '.join(unknown_options)}",
            )

    @staticmethod
    def _render(values: dict[str, str]) -> str:
        lines = [f"schema_version = {CONFIG_SCHEMA_VERSION}"]
        sections = sorted(
            {option.section for option in ConfigurationCatalog.OPTIONS.values()}
        )
        for section in sections:
            options = [
                option
                for option in ConfigurationCatalog.OPTIONS.values()
                if option.section == section and option.key in values
            ]
            if not options:
                continue
            lines.extend(["", f"[{section}]"])
            for option in sorted(options, key=lambda item: item.name):
                rendered = json.dumps(values[option.key], ensure_ascii=False)
                lines.append(f"{option.name} = {rendered}")
        return "\n".join(lines) + "\n"
