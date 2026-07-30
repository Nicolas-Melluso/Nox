"""Persistencia y resolución de los feature flags de Nox."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from nox_agent.config import ConfigScope
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.feature_flags.catalog import (
    FeatureFlagCatalog,
    FeatureFlagValue,
)
from nox_agent.feature_flags.document import (
    DEFAULTS_FILENAME,
    FeatureFlagDocument,
)
from nox_agent.project import ProjectContext, find_active_project

FEATURE_FLAGS_FILENAME = "feature_flags.yaml"


@dataclass(frozen=True)
class EffectiveFeatureFlagValue:
    key: str
    value: FeatureFlagValue
    source: str
    default_value: FeatureFlagValue
    global_value: FeatureFlagValue | None
    local_value: FeatureFlagValue | None

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "source": self.source,
            "default": self.default_value,
            "global": self.global_value,
            "local": self.local_value,
        }


@dataclass(frozen=True)
class EffectiveFeatureFlags:
    environment: str
    values: dict[str, EffectiveFeatureFlagValue]
    project: ProjectContext | None

    def get(self, key: str) -> FeatureFlagValue:
        FeatureFlagCatalog.definition(key)
        return self.values[key].value

    def to_dict(self) -> dict[str, object]:
        project = None
        if self.project is not None:
            project = {
                "id": self.project.manifest.project_id,
                "name": self.project.manifest.name,
                "root": str(self.project.root),
            }
        return {
            "environment": self.environment,
            "values": {
                key: value.to_dict()
                for key, value in self.values.items()
            },
            "project": project,
        }


class FeatureFlagManager:
    """Combina defaults, overrides globales y overrides del proyecto activo."""

    def __init__(self, start: Path) -> None:
        self.start = start.resolve()
        self.project = find_active_project(self.start)
        self.environment, self.defaults = FeatureFlagDocument.read_defaults(
            self.defaults_path(),
        )

    def effective(self) -> EffectiveFeatureFlags:
        global_values = FeatureFlagDocument.read_overrides(self.global_path())
        local_values = (
            FeatureFlagDocument.read_overrides(self.local_path())
            if self.project is not None
            else {}
        )
        values: dict[str, EffectiveFeatureFlagValue] = {}

        for key in FeatureFlagCatalog.keys():
            default_value = self.defaults[key]
            global_value = global_values.get(key)
            local_value = local_values.get(key)
            if key in local_values:
                value = local_values[key]
                source = ConfigScope.LOCAL.value
            elif key in global_values:
                value = global_values[key]
                source = ConfigScope.GLOBAL.value
            else:
                value = default_value
                source = "default"
            values[key] = EffectiveFeatureFlagValue(
                key=key,
                value=value,
                source=source,
                default_value=default_value,
                global_value=global_value,
                local_value=local_value,
            )

        return EffectiveFeatureFlags(
            environment=self.environment,
            values=values,
            project=self.project,
        )

    def set(
        self,
        key: str,
        value: object,
        scope: ConfigScope,
    ) -> FeatureFlagValue:
        normalized = FeatureFlagCatalog.definition(key).validate(value)
        path = self.path_for_scope(scope)
        values = FeatureFlagDocument.read_overrides(path)
        values[key] = normalized
        FeatureFlagDocument.write_overrides(path, values)
        return normalized

    def unset(
        self,
        key: str,
        scope: ConfigScope,
    ) -> FeatureFlagValue | None:
        FeatureFlagCatalog.definition(key)
        path = self.path_for_scope(scope)
        values = FeatureFlagDocument.read_overrides(path)
        removed = values.pop(key, None)
        if removed is not None:
            FeatureFlagDocument.write_overrides(path, values)
        return removed

    def values_for_scope(
        self,
        scope: ConfigScope,
    ) -> dict[str, FeatureFlagValue]:
        return FeatureFlagDocument.read_overrides(
            self.path_for_scope(scope),
        )

    def path_for_scope(self, scope: ConfigScope) -> Path:
        return self.global_path() if scope == ConfigScope.GLOBAL else self.local_path()

    @staticmethod
    def global_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise NoxErrorFactory.create(
                ErrorCode.FEATURE_FLAGS_INVALID,
                detail="Windows no informó la ubicación LOCALAPPDATA.",
            )
        return Path(local_app_data) / "Nox" / FEATURE_FLAGS_FILENAME

    def local_path(self) -> Path:
        if self.project is None:
            raise NoxErrorFactory.create(
                ErrorCode.LOCAL_PROJECT_REQUIRED,
                detail="Ejecutá nox init antes de guardar feature flags locales.",
            )
        return self.project.root / ".nox" / FEATURE_FLAGS_FILENAME

    @staticmethod
    def defaults_path() -> Path:
        return Path(__file__).with_name(DEFAULTS_FILENAME)
