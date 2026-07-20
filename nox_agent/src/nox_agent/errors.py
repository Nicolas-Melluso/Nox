"""Catálogo y construcción centralizada de errores de Nox."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Código estable junto con el mensaje público asociado."""

    message: str

    def __new__(cls, code: str, message: str) -> "ErrorCode":
        member = str.__new__(cls, code)
        member._value_ = code
        member.message = message
        return member

    UNKNOWN_CRITICAL = (
        "EN0178000",
        "Nox encontró un error crítico que todavía no está identificado.",
    )
    INVALID_NOX_DIRECTORY = (
        "EN0178001",
        "La carpeta .nox no es válida.",
    )
    MANIFEST_MISSING = (
        "EN0178002",
        "La carpeta .nox no contiene project.toml.",
    )
    MANIFEST_INVALID_TOML = (
        "EN0178003",
        "El archivo project.toml no contiene TOML válido.",
    )
    MANIFEST_INVALID_SCHEMA = (
        "EN0178004",
        "El esquema de project.toml no es válido o no es compatible.",
    )
    MANIFEST_INVALID_PROJECT_ID = (
        "EN0178005",
        "project_id debe ser un UUID válido.",
    )
    MANIFEST_INVALID_NAME = (
        "EN0178006",
        "name debe ser un texto no vacío.",
    )
    MANIFEST_INVALID_CREATED_AT = (
        "EN0178007",
        "created_at debe ser una fecha y hora UTC válida.",
    )
    PARENT_DECLARATION_INVALID = (
        "EN0178008",
        "La declaración del proyecto padre no es válida.",
    )
    PARENT_RELATIONSHIP_INVALID = (
        "EN0178009",
        "La relación entre el proyecto hijo y su padre no es válida.",
    )
    FILESYSTEM_ERROR = (
        "EN0178010",
        "Nox no pudo completar una operación de archivos.",
    )
    REGISTRY_INVALID = (
        "EN0178011",
        "El registro global de proyectos no es válido.",
    )
    REGISTRY_WRITE_FAILED = (
        "EN0178012",
        "Nox no pudo actualizar el registro global de proyectos.",
    )
    CONFIG_INVALID = (
        "EN0178013",
        "La configuración de Nox no es válida.",
    )
    CONFIG_VALUE_INVALID = (
        "EN0178014",
        "El valor indicado para la configuración no es válido.",
    )
    LOCAL_PROJECT_REQUIRED = (
        "EN0178015",
        "La configuración local requiere un proyecto Nox.",
    )
    INTERACTIVE_TERMINAL_REQUIRED = (
        "EN0178016",
        "El menú interactivo requiere una terminal compatible.",
    )
    SESSION_PROJECT_REQUIRED = (
        "EN0178017",
        "Nox solamente puede iniciar una sesión dentro de un proyecto válido.",
    )
    MODEL_NOT_CONFIGURED = (
        "EN0178018",
        "No hay un modelo configurado para la sesión.",
    )
    MODEL_PROVIDER_UNAVAILABLE = (
        "EN0178019",
        "Nox no pudo comunicarse con el proveedor del modelo.",
    )
    MODEL_RESPONSE_INVALID = (
        "EN0178020",
        "El proveedor devolvió una respuesta que Nox no puede interpretar.",
    )
    SESSION_TERMINAL_REQUIRED = (
        "EN0178021",
        "La sesión interactiva requiere una terminal compatible.",
    )


class NoxError(Exception):
    """Error controlado que Nox puede explicar al usuario."""

    def __init__(self, code: ErrorCode, *, detail: str | None = None) -> None:
        super().__init__(code.message)
        self.code = code
        self.message = code.message
        self.detail = detail

    def format_for_cli(self) -> str:
        lines = [f"[{self.code}] {self.message}"]
        if self.detail:
            lines.append(f"Detalle: {self.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": str(self.code),
            "message": self.message,
            "detail": self.detail,
        }


class NoxErrorFactory:
    """Crea errores usando el código como única fuente del mensaje público."""

    @staticmethod
    def create(
        code: ErrorCode,
        *,
        detail: str | None = None,
    ) -> NoxError:
        return NoxError(code, detail=detail)
