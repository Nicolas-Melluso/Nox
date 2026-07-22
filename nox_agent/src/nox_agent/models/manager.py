"""Contratos compartidos para administrar modelos de cualquier proveedor."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from nox_agent.errors import ErrorCode, NoxError

ProgressHandler = Callable[[str, int | None, int | None], None]


@dataclass(frozen=True)
class InstalledModel:
    name: str
    size: int | None
    digest: str | None
    modified_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "size": self.size,
            "digest": self.digest,
            "modified_at": self.modified_at,
        }


class ModelManager(ABC):
    """Contrato operativo para listar, descargar y eliminar modelos."""

    @abstractmethod
    def list(self) -> list[InstalledModel]:
        """Devuelve los modelos disponibles en el proveedor."""

    @abstractmethod
    def pull(
        self,
        name: str,
        *,
        on_progress: ProgressHandler | None = None,
    ) -> None:
        """Descarga un modelo y solo retorna cuando terminó correctamente."""

    @abstractmethod
    def remove(self, name: str) -> None:
        """Elimina un modelo existente."""

    def find(
        self,
        name: str,
        models: list[InstalledModel] | None = None,
    ) -> InstalledModel | None:
        available = self.list() if models is None else models
        return next(
            (model for model in available if self.matches(model.name, name)),
            None,
        )

    def contains(self, name: str) -> bool:
        return self.find(name) is not None

    def matches(self, first: str, second: str) -> bool:
        return bool(first and second) and first.strip().casefold() == second.strip().casefold()

    def wait_until_available(
        self,
        *,
        timeout_seconds: float = 20,
        interval_seconds: float = 0.5,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                self.list()
                return True
            except NoxError as error:
                if error.code != ErrorCode.MODEL_PROVIDER_UNAVAILABLE:
                    raise
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval_seconds)


def format_model_size(value: object) -> str:
    if not isinstance(value, int):
        return "Tamaño desconocido"
    return f"{value / (1024**3):.2f} GiB"
