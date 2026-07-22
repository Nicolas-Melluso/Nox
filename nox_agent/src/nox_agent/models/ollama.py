"""Integración completa del proveedor Ollama con Nox."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Never
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nox_agent.engines import OllamaEngine
from nox_agent.engines.setup import OllamaSetup
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.logs import NoxLogs
from nox_agent.models.manager import InstalledModel, ModelManager, ProgressHandler
from nox_agent.models.provider import ChatMessage, ModelProvider, TokenHandler
from nox_agent.tools import ConsoleMenu

REQUEST_TIMEOUT_SECONDS = 120
RECOMMENDED_MODEL = "qwen3:4b"
logger = NoxLogs.get_logger("models.ollama")


class _OllamaClient:
    """Cliente HTTP compartido por conversación y administración."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float = 30,
        error_code: ErrorCode = ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
    ) -> object:
        request = self._request(method, path, payload)
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            self._request_error(error_code, f"HTTP {error.code} | {detail}")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            self._request_error(error_code, str(error))

    def stream_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        error_code: ErrorCode,
    ) -> Iterator[dict[str, object]]:
        request = self._request("POST", path, payload)
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                for raw_line in response:
                    if not raw_line.strip():
                        continue
                    chunk = json.loads(raw_line)
                    if isinstance(chunk, dict):
                        yield chunk
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            self._request_error(error_code, f"HTTP {error.code} | {detail}")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            self._request_error(error_code, str(error))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> Request:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        return Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )

    def _request_error(self, code: ErrorCode, diagnostic: str) -> Never:
        logger.debug("Ollama no respondió en %s: %s", self.base_url, diagnostic)
        detail = (
            f"Ollama no respondió en {self.base_url}. "
            "Verificá que la aplicación esté abierta y el servicio iniciado."
        )
        if code == ErrorCode.MODEL_DOWNLOAD_FAILED:
            detail = f"No se pudo descargar el modelo desde {self.base_url}."
        raise NoxErrorFactory.create(code, detail=detail)


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, *, model: str, base_url: str) -> None:
        self.model = model
        self.client = _OllamaClient(base_url)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        on_token: TokenHandler | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
            "stream": True,
        }
        parts: list[str] = []
        for chunk in self.client.stream_json(
            "/api/chat",
            payload,
            error_code=ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
        ):
            error_message = chunk.get("error")
            if isinstance(error_message, str):
                raise NoxErrorFactory.create(
                    ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
                    detail=f"Ollama: {error_message}",
                )
            message = chunk.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content", "")
            if not isinstance(content, str):
                raise NoxErrorFactory.create(
                    ErrorCode.MODEL_RESPONSE_INVALID,
                    detail="message.content no es texto.",
                )
            if content:
                parts.append(content)
                if on_token is not None:
                    on_token(content)

        answer = "".join(parts)
        if not answer:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="Ollama no devolvió contenido para la respuesta.",
            )
        return answer


class OllamaModelManager(ModelManager):
    """Administra los modelos publicados en una instancia de Ollama."""

    def __init__(self, base_url: str) -> None:
        self.client = _OllamaClient(base_url)

    def list(self) -> list[InstalledModel]:
        data = self.client.json_request("GET", "/api/tags")
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="Ollama no devolvió una lista de modelos.",
            )
        result: list[InstalledModel] = []
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                continue
            size = model.get("size")
            digest = model.get("digest")
            modified_at = model.get("modified_at")
            result.append(
                InstalledModel(
                    name=model["name"],
                    size=size if isinstance(size, int) else None,
                    digest=digest if isinstance(digest, str) else None,
                    modified_at=modified_at if isinstance(modified_at, str) else None,
                )
            )
        return sorted(result, key=lambda item: item.name.casefold())

    def pull(
        self,
        name: str,
        *,
        on_progress: ProgressHandler | None = None,
    ) -> None:
        completed = False
        for chunk in self.client.stream_json(
            "/api/pull",
            {"model": name, "stream": True},
            error_code=ErrorCode.MODEL_DOWNLOAD_FAILED,
        ):
            error_message = chunk.get("error")
            if isinstance(error_message, str):
                self._download_error(error_message)
            status = chunk.get("status")
            if isinstance(status, str) and status.casefold() == "success":
                completed = True
            if on_progress is not None:
                completed_bytes = chunk.get("completed")
                total = chunk.get("total")
                on_progress(
                    status if isinstance(status, str) else "descargando",
                    completed_bytes if isinstance(completed_bytes, int) else None,
                    total if isinstance(total, int) else None,
                )
        if not completed:
            self._download_error("Ollama cerró la descarga sin confirmar éxito.")

    def remove(self, name: str) -> None:
        installed = self.find(name)
        if installed is None:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_FOUND,
                detail=f"Modelo: {name}",
            )
        try:
            self.client.json_request(
                "DELETE",
                "/api/delete",
                {"model": installed.name},
            )
        except NoxError as error:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_DELETE_FAILED,
                detail=error.detail or error.message,
            ) from error

    def wait_until_available(
        self,
        *,
        timeout_seconds: float = 20,
        interval_seconds: float = 0.5,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                self.client.json_request(
                    "GET",
                    "/api/tags",
                    timeout=min(1.0, remaining),
                )
                return True
            except NoxError as error:
                if error.code != ErrorCode.MODEL_PROVIDER_UNAVAILABLE:
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(interval_seconds, remaining))

    def matches(self, first: str, second: str) -> bool:
        if not first or not second:
            return False

        def canonical(value: str) -> str:
            normalized = value.strip().casefold()
            return normalized if ":" in normalized else f"{normalized}:latest"

        return canonical(first) == canonical(second)

    @staticmethod
    def _download_error(detail: str) -> Never:
        raise NoxErrorFactory.create(ErrorCode.MODEL_DOWNLOAD_FAILED, detail=detail)


class OllamaIntegration:
    """Encapsula todas las decisiones específicas de Ollama."""

    name = "ollama"
    recommended_model = RECOMMENDED_MODEL

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")

    def create_provider(self, model: str) -> ModelProvider:
        return OllamaProvider(model=model, base_url=self.endpoint)

    def create_manager(self) -> ModelManager:
        return OllamaModelManager(self.endpoint)

    def ensure_engine(self, menu: ConsoleMenu) -> bool | None:
        return OllamaSetup(menu).ensure(self.endpoint)

    def recover_service(self, menu: ConsoleMenu, manager: ModelManager) -> bool:
        return OllamaSetup(menu).recover_service(
            self.endpoint,
            lambda: manager.wait_until_available(timeout_seconds=0.1),
            lambda: manager.wait_until_available(timeout_seconds=20),
        )

    def require_engine(self) -> None:
        if (
            OllamaEngine.is_local_endpoint(self.endpoint)
            and OllamaEngine.executable_path() is None
        ):
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_NOT_INSTALLED,
                detail=(
                    "Instalalo desde `nox models`, eligiendo "
                    "‘Preparar inteligencia local’, o con "
                    "`nox engines install ollama`."
                ),
            )
