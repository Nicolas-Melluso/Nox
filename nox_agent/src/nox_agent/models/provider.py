"""Contrato agnóstico para proveedores de modelos."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from nox_agent.config.manager import EffectiveConfiguration
from nox_agent.errors import ErrorCode, NoxErrorFactory

TokenHandler = Callable[[str], None]


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ModelProvider(ABC):
    """Interfaz que el motor usa sin conocer el proveedor concreto."""

    name: str
    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        on_token: TokenHandler | None = None,
    ) -> str:
        """Genera la siguiente respuesta y opcionalmente transmite fragmentos."""

    @abstractmethod
    def available_models(self) -> list[str]:
        """Lista los modelos instalados en el proveedor."""


class ProviderFactory:
    """Construye el adaptador indicado por la configuración actual."""

    @staticmethod
    def create(configuration: EffectiveConfiguration) -> ModelProvider:
        values = configuration.values
        provider = values["models.provider"].value
        model = values["models.model"].value
        if not model:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_CONFIGURED,
                detail=(
                    "Configurá uno con: nox config models "
                    "--provider ollama --model <nombre> --scope global"
                ),
            )
        if provider == "ollama":
            from nox_agent.models.ollama import OllamaProvider

            return OllamaProvider(
                model=model,
                base_url=values["models.ollama_url"].value,
            )
        raise NoxErrorFactory.create(
            ErrorCode.CONFIG_VALUE_INVALID,
            detail=f"Proveedor no soportado: {provider}",
        )
