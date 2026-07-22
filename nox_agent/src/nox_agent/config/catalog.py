"""Definiciones declarativas de las opciones de configuración."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Never
from urllib.parse import urlparse

from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.logs import LogLevel


class ConfigScope(StrEnum):
    GLOBAL = "global"
    LOCAL = "local"


class ConfigSectionStatus(StrEnum):
    AVAILABLE = "available"
    UPCOMING = "upcoming"


class ConfigValueKind(StrEnum):
    CHOICE = "choice"
    TEXT = "text"
    URL = "url"


@dataclass(frozen=True)
class ConfigSection:
    key: str
    title: str
    status: ConfigSectionStatus
    description: str


@dataclass(frozen=True)
class ConfigOption:
    key: str
    section: str
    name: str
    default: str
    kind: ConfigValueKind
    scopes: frozenset[ConfigScope]
    description: str
    choices: tuple[str, ...] = ()

    def normalize(self, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            self._invalid(f"requiere un texto no vacío. Recibido: {value!r}")
        normalized = value.strip()
        if self.kind == ConfigValueKind.CHOICE:
            canonical = {choice.casefold(): choice for choice in self.choices}
            selected = canonical.get(normalized.casefold())
            if selected is None:
                self._invalid(f"valores permitidos: {', '.join(self.choices)}")
            return selected
        if self.kind == ConfigValueKind.URL:
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                self._invalid("requiere una URL http o https completa")
            return normalized.rstrip("/")
        return normalized

    def _invalid(self, reason: str) -> Never:
        raise NoxErrorFactory.create(
            ErrorCode.CONFIG_VALUE_INVALID,
            detail=f"{self.key}: {reason}.",
        )


class ConfigurationCatalog:
    """Única fuente de secciones y opciones configurables."""

    ALL_SCOPES = frozenset({ConfigScope.GLOBAL, ConfigScope.LOCAL})
    SECTIONS = (
        ConfigSection(
            "logs",
            "Logs",
            ConfigSectionStatus.AVAILABLE,
            "Nivel de detalle de los diagnósticos de Nox.",
        ),
        ConfigSection(
            "memory",
            "Memory",
            ConfigSectionStatus.UPCOMING,
            "Memoria del agente y retención de contexto.",
        ),
        ConfigSection(
            "models",
            "Models",
            ConfigSectionStatus.AVAILABLE,
            "Modelo y proveedor de inferencia usado por Nox.",
        ),
        ConfigSection(
            "security",
            "Security",
            ConfigSectionStatus.UPCOMING,
            "Permisos y políticas de ejecución.",
        ),
    )
    OPTIONS = {
        "logs.level": ConfigOption(
            "logs.level",
            "logs",
            "level",
            LogLevel.INFO.value,
            ConfigValueKind.CHOICE,
            ALL_SCOPES,
            "Nivel mínimo de logs emitidos por Nox.",
            tuple(level.value for level in LogLevel),
        ),
        "models.provider": ConfigOption(
            "models.provider",
            "models",
            "provider",
            "ollama",
            ConfigValueKind.TEXT,
            ALL_SCOPES,
            "Proveedor de inferencia.",
        ),
        "models.model": ConfigOption(
            "models.model",
            "models",
            "model",
            "",
            ConfigValueKind.TEXT,
            ALL_SCOPES,
            "Nombre exacto del modelo.",
        ),
        "models.ollama_url": ConfigOption(
            "models.ollama_url",
            "models",
            "ollama_url",
            "http://127.0.0.1:11434",
            ConfigValueKind.URL,
            ALL_SCOPES,
            "Dirección del servicio local de Ollama.",
        ),
    }

    @classmethod
    def option(cls, key: str) -> ConfigOption:
        option = cls.OPTIONS.get(key)
        if option is None:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_INVALID,
                detail=f"Opción desconocida: {key}",
            )
        return option

    @classmethod
    def options_for_section(cls, section: str) -> tuple[ConfigOption, ...]:
        return tuple(option for option in cls.OPTIONS.values() if option.section == section)

    @classmethod
    def sections_as_dict(cls) -> list[dict[str, str]]:
        return [
            {
                "key": section.key,
                "title": section.title,
                "status": section.status.value,
                "description": section.description,
            }
            for section in cls.SECTIONS
        ]
