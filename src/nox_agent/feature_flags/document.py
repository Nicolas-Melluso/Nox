"""Lectura, validación y escritura de documentos YAML de feature flags."""

from pathlib import Path
from typing import NoReturn

import yaml

from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.feature_flags.catalog import (
    FeatureFlagCatalog,
    FeatureFlagValue,
)
from nox_agent.tools import FileManager

FEATURE_FLAGS_SCHEMA_VERSION = 1
DEFAULTS_FILENAME = "defaults.yaml"
DEFAULT_ENVIRONMENT = "development"


class FeatureFlagDocument:
    """Mantiene el formato YAML fuera de la resolución de precedencias."""

    @classmethod
    def read_defaults(
        cls,
        path: Path,
    ) -> tuple[str, dict[str, FeatureFlagValue]]:
        data = cls._load_yaml(path, required=True)
        cls._validate_top_level(
            data,
            path=path,
            allow_environment=True,
        )
        received_environment = data.get("environment")
        if received_environment != DEFAULT_ENVIRONMENT:
            cls._invalid(
                path,
                f"environment debe ser {DEFAULT_ENVIRONMENT!r}",
            )

        values = cls._validate_flags(data.get("flags"), path)
        expected = set(FeatureFlagCatalog.keys())
        received = set(values)
        if received != expected:
            missing = sorted(expected - received)
            extra = sorted(received - expected)
            details: list[str] = []
            if missing:
                details.append(f"faltan: {', '.join(missing)}")
            if extra:
                details.append(f"sobran: {', '.join(extra)}")
            cls._invalid(path, "; ".join(details))
        return DEFAULT_ENVIRONMENT, values

    @classmethod
    def read_overrides(
        cls,
        path: Path,
    ) -> dict[str, FeatureFlagValue]:
        if not path.exists():
            return {}
        data = cls._load_yaml(path, required=False)
        if not data:
            return {}
        cls._validate_top_level(
            data,
            path=path,
            allow_environment=False,
        )
        return cls._validate_flags(data.get("flags", {}), path)

    @staticmethod
    def write_overrides(
        path: Path,
        values: dict[str, FeatureFlagValue],
    ) -> None:
        ordered = {
            key: values[key]
            for key in FeatureFlagCatalog.keys()
            if key in values
        }
        document = {
            "schema_version": FEATURE_FLAGS_SCHEMA_VERSION,
            "flags": ordered,
        }
        try:
            content = yaml.safe_dump(
                document,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            FileManager.atomic_write_text(
                path,
                content,
                create_parents=True,
            )
        except (OSError, yaml.YAMLError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.FEATURE_FLAGS_INVALID,
                detail=f"Escribir {path}: {error}",
            ) from error

    @classmethod
    def _load_yaml(
        cls,
        path: Path,
        *,
        required: bool,
    ) -> dict[object, object]:
        if not path.exists():
            if not required:
                return {}
            cls._invalid(path, "no se encontró el archivo requerido")
        if not path.is_file():
            cls._invalid(path, "la ruta no es un archivo")
        try:
            with path.open("r", encoding="utf-8") as yaml_file:
                loaded = yaml.safe_load(yaml_file)
        except (OSError, yaml.YAMLError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.FEATURE_FLAGS_INVALID,
                detail=f"Leer {path}: {error}",
            ) from error
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            cls._invalid(path, "el documento YAML debe ser un objeto")
        return loaded

    @classmethod
    def _validate_top_level(
        cls,
        data: dict[object, object],
        *,
        path: Path,
        allow_environment: bool,
    ) -> None:
        allowed = {"schema_version", "flags"}
        if allow_environment:
            allowed.add("environment")
        unknown = sorted(
            repr(key)
            for key in data
            if key not in allowed
        )
        if unknown:
            cls._invalid(
                path,
                f"claves desconocidas: {', '.join(unknown)}",
            )
        if data.get("schema_version") != FEATURE_FLAGS_SCHEMA_VERSION:
            cls._invalid(
                path,
                (
                    f"schema_version esperado {FEATURE_FLAGS_SCHEMA_VERSION}, "
                    f"recibido {data.get('schema_version')!r}"
                ),
            )

    @classmethod
    def _validate_flags(
        cls,
        raw_flags: object,
        path: Path,
    ) -> dict[str, FeatureFlagValue]:
        if not isinstance(raw_flags, dict):
            cls._invalid(path, "flags debe ser un objeto YAML")
        values: dict[str, FeatureFlagValue] = {}
        for key, value in raw_flags.items():
            if not isinstance(key, str):
                cls._invalid(path, "cada clave de flags debe ser texto")
            values[key] = FeatureFlagCatalog.definition(key).validate(value)
        return values

    @staticmethod
    def _invalid(path: Path, reason: str) -> NoReturn:
        raise NoxErrorFactory.create(
            ErrorCode.FEATURE_FLAGS_INVALID,
            detail=f"{path}: {reason}.",
        )
