"""Catálogo y validación de los feature flags conocidos por Nox."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Never

from nox_agent.errors import ErrorCode, NoxErrorFactory

FeatureFlagValue = bool | int | str


class FeatureFlagKind(StrEnum):
    BOOLEAN = "boolean"
    CHOICE = "choice"
    INTEGER = "integer"


@dataclass(frozen=True)
class FeatureFlagDefinition:
    key: str
    kind: FeatureFlagKind
    description: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None

    def validate(self, value: object) -> FeatureFlagValue:
        if self.kind == FeatureFlagKind.BOOLEAN:
            if not isinstance(value, bool):
                self._invalid("requiere true o false")
            return value

        if self.kind == FeatureFlagKind.CHOICE:
            if not isinstance(value, str):
                self._invalid(
                    f"valores permitidos: {', '.join(self.choices)}"
                )
            canonical = {choice.casefold(): choice for choice in self.choices}
            selected = canonical.get(value.strip().casefold())
            if selected is None:
                self._invalid(
                    f"valores permitidos: {', '.join(self.choices)}"
                )
            return selected

        if isinstance(value, bool) or not isinstance(value, int):
            self._invalid("requiere un número entero")
        if self.minimum is not None and value < self.minimum:
            self._invalid(f"el mínimo permitido es {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            self._invalid(f"el máximo permitido es {self.maximum}")
        return value

    def parse_cli(self, value: str) -> FeatureFlagValue:
        normalized = value.strip()
        if self.kind == FeatureFlagKind.BOOLEAN:
            boolean_values = {
                "true": True,
                "on": True,
                "false": False,
                "off": False,
            }
            selected = boolean_values.get(normalized.casefold())
            if selected is None:
                self._invalid("usá true, false, on u off")
            return selected

        if self.kind == FeatureFlagKind.INTEGER:
            try:
                parsed = int(normalized, 10)
            except ValueError:
                self._invalid("requiere un número entero")
            return self.validate(parsed)

        return self.validate(normalized)

    def to_dict(self, *, default: FeatureFlagValue) -> dict[str, object]:
        data: dict[str, object] = {
            "key": self.key,
            "kind": self.kind.value,
            "description": self.description,
            "default": default,
        }
        if self.choices:
            data["choices"] = list(self.choices)
        if self.minimum is not None:
            data["minimum"] = self.minimum
        if self.maximum is not None:
            data["maximum"] = self.maximum
        return data

    def _invalid(self, reason: str) -> Never:
        raise NoxErrorFactory.create(
            ErrorCode.FEATURE_FLAGS_INVALID,
            detail=f"{self.key}: {reason}.",
        )


class FeatureFlagCatalog:
    """Única fuente de claves, tipos y límites admitidos."""

    DEFINITIONS = (
        FeatureFlagDefinition(
            "audit.enabled",
            FeatureFlagKind.BOOLEAN,
            "Habilita el registro estructurado de auditoría.",
        ),
        FeatureFlagDefinition(
            "audit.level",
            FeatureFlagKind.CHOICE,
            "Define cuánto detalle conserva la auditoría.",
            choices=("off", "metadata", "activity", "full"),
        ),
        FeatureFlagDefinition(
            "audit.retention_hours",
            FeatureFlagKind.INTEGER,
            "Cantidad de horas que se conserva la auditoría.",
            minimum=1,
            maximum=8760,
        ),
        FeatureFlagDefinition(
            "transcription.enabled",
            FeatureFlagKind.BOOLEAN,
            "Habilita capacidades de transcripción.",
        ),
        FeatureFlagDefinition(
            "metrics.enabled",
            FeatureFlagKind.BOOLEAN,
            "Habilita la recolección de métricas.",
        ),
        FeatureFlagDefinition(
            "metrics.timings",
            FeatureFlagKind.BOOLEAN,
            "Habilita métricas de duración.",
        ),
        FeatureFlagDefinition(
            "logs.enabled",
            FeatureFlagKind.BOOLEAN,
            "Habilita los logs operativos.",
        ),
        FeatureFlagDefinition(
            "logs.persistent",
            FeatureFlagKind.BOOLEAN,
            "Habilita la persistencia de logs.",
        ),
    )
    _BY_KEY = {definition.key: definition for definition in DEFINITIONS}

    @classmethod
    def definition(cls, key: str) -> FeatureFlagDefinition:
        definition = cls._BY_KEY.get(key)
        if definition is None:
            raise NoxErrorFactory.create(
                ErrorCode.FEATURE_FLAG_UNKNOWN,
                detail=f"Feature flag desconocido: {key}",
            )
        return definition

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(definition.key for definition in cls.DEFINITIONS)
