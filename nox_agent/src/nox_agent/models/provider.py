"""Contrato agnóstico para proveedores de modelos."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from nox_agent.models.manager import ModelManager
from nox_agent.tools import ConsoleMenu

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

    def prepare(self) -> None:
        """Prepara el proveedor para reducir la latencia del primer turno."""
        return None

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        on_token: TokenHandler | None = None,
    ) -> str:
        """Genera la siguiente respuesta y opcionalmente transmite fragmentos."""

    @abstractmethod
    def generate_structured(
        self,
        messages: list[ChatMessage],
        *,
        schema: Mapping[str, object],
    ) -> object:
        """Genera datos estructurados según un esquema controlado por Nox."""


class ProviderIntegration(Protocol):
    """Une conversación, modelos y motor sin filtrarlos al núcleo de Nox."""

    @property
    def name(self) -> str: ...

    @property
    def endpoint(self) -> str: ...

    @property
    def recommended_model(self) -> str | None: ...

    def create_provider(self, model: str) -> ModelProvider: ...

    def create_manager(self) -> ModelManager: ...

    def ensure_engine(self, menu: ConsoleMenu) -> bool | None: ...

    def recover_service(self, menu: ConsoleMenu, manager: ModelManager) -> bool: ...

    def require_engine(self) -> None: ...
