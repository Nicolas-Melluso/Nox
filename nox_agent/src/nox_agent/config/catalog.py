"""Definiciones declarativas de las opciones de configuración."""

from dataclasses import dataclass
from enum import StrEnum

from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.logs import LogLevel


class ConfigScope(StrEnum):
    GLOBAL = "global"
    LOCAL = "local"


class ConfigSectionStatus(StrEnum):
    AVAILABLE = "available"
    UPCOMING = "upcoming"


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
    choices: tuple[str, ...]
    scopes: frozenset[ConfigScope]
    description: str

    def normalize(self, value: object) -> str:
        if not isinstance(value, str):
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_VALUE_INVALID,
                detail=f"{self.key} requiere texto. Recibido: {value!r}",
            )
        normalized = value.strip().upper()
        if normalized not in self.choices:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_VALUE_INVALID,
                detail=(
                    f"{self.key}: {value!r}. "
                    f"Valores permitidos: {', '.join(self.choices)}"
                ),
            )
        return normalized


class ConfigurationCatalog:
    """Única fuente de secciones y opciones configurables."""

    SECTIONS = (
        ConfigSection(
            key="logs",
            title="Logs",
            status=ConfigSectionStatus.AVAILABLE,
            description="Nivel de detalle de los diagnósticos de Nox.",
        ),
        ConfigSection(
            key="memory",
            title="Memory",
            status=ConfigSectionStatus.UPCOMING,
            description="Memoria del agente y retención de contexto.",
        ),
        ConfigSection(
            key="models",
            title="Models",
            status=ConfigSectionStatus.UPCOMING,
            description="Modelos y proveedores de inferencia.",
        ),
        ConfigSection(
            key="security",
            title="Security",
            status=ConfigSectionStatus.UPCOMING,
            description="Permisos y políticas de ejecución.",
        ),
    )

    OPTIONS = {
        "logs.level": ConfigOption(
            key="logs.level",
            section="logs",
            name="level",
            default=LogLevel.INFO.value,
            choices=tuple(level.value for level in LogLevel),
            scopes=frozenset({ConfigScope.GLOBAL, ConfigScope.LOCAL}),
            description="Nivel mínimo de logs emitidos por Nox.",
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
