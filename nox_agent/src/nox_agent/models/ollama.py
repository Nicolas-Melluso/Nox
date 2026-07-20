"""Adaptador del contrato de Nox para la API local de Ollama."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models.provider import ChatMessage, ModelProvider, TokenHandler

REQUEST_TIMEOUT_SECONDS = 120


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, *, model: str, base_url: str) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        on_token: TokenHandler | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
            "stream": True,
        }
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        parts: list[str] = []
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                for raw_line in response:
                    content = self._read_chunk(raw_line)
                    if content:
                        parts.append(content)
                        if on_token is not None:
                            on_token(content)
        except NoxError:
            raise
        except HTTPError as error:
            detail = self._http_error_detail(error)
            raise self._unavailable(detail) from error
        except (URLError, TimeoutError, OSError) as error:
            raise self._unavailable(str(error)) from error

        answer = "".join(parts)
        if not answer:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="Ollama no devolvió contenido para la respuesta.",
            )
        return answer

    def available_models(self) -> list[str]:
        request = Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                data = json.load(response)
        except HTTPError as error:
            raise self._unavailable(self._http_error_detail(error)) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise self._unavailable(str(error)) from error

        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="Ollama no devolvió una lista de modelos.",
            )
        return sorted(
            model["name"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("name"), str)
        )

    @staticmethod
    def _read_chunk(raw_line: bytes) -> str:
        if not raw_line.strip():
            return ""
        try:
            chunk = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail=f"Fragmento JSON inválido: {error}",
            ) from error
        if not isinstance(chunk, dict):
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="Un fragmento de Ollama no es un objeto JSON.",
            )
        if isinstance(chunk.get("error"), str):
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
                detail=f"Ollama: {chunk['error']}",
            )
        message = chunk.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content", "")
        if not isinstance(content, str):
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_RESPONSE_INVALID,
                detail="message.content no es texto.",
            )
        return content

    def _unavailable(self, detail: str) -> NoxError:
        return NoxErrorFactory.create(
            ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
            detail=f"{self.base_url} | {detail}",
        )

    @staticmethod
    def _http_error_detail(error: HTTPError) -> str:
        try:
            body = error.read().decode("utf-8", errors="replace").strip()
        except OSError:
            body = ""
        return f"HTTP {error.code}{f' | {body}' if body else ''}"
