"""Sesión conversacional interactiva de Nox."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from nox_agent.config import ConfigurationManager, EffectiveConfiguration
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import ChatMessage, ModelProvider, ProviderFactory
from nox_agent.registry import register_context
from nox_agent.runtime.status import StatusService


class ReplSession:
    """Mantiene una conversación temporal dentro de un proyecto Nox."""

    def __init__(
        self,
        start: Path,
        *,
        nox_version: str,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        require_tty: bool = True,
    ) -> None:
        self.start = start.resolve()
        self.nox_version = nox_version
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self.require_tty = require_tty
        self.provider: ModelProvider | None = None
        self.history: list[ChatMessage] = []

    def run(self) -> int:
        manager = ConfigurationManager(self.start)
        if manager.project is None:
            raise NoxErrorFactory.create(
                ErrorCode.SESSION_PROJECT_REQUIRED,
                detail="Ejecutá nox init en el proyecto antes de usar nox start.",
            )
        if self.require_tty and (
            not self.input.isatty() or not self.output.isatty()
        ):
            raise NoxErrorFactory.create(ErrorCode.SESSION_TERMINAL_REQUIRED)
        register_context(manager.project)
        configuration = manager.effective()
        self.provider = self._create_provider(configuration)
        self._reset_history()
        self._print_banner()

        while True:
            try:
                text = self._read_line("nox> ")
            except KeyboardInterrupt:
                self._write("\nEntrada cancelada. Usá /exit para salir.\n")
                continue
            if text is None:
                self._write("\nSesión finalizada.\n")
                return 0

            text = text.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._run_internal_command(text):
                    return 0
                continue
            self._respond(text)

    def _respond(self, text: str) -> None:
        if self.provider is None:
            error = NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_CONFIGURED,
                detail=(
                    "Usá nox config models --model <nombre> --scope global "
                    "antes de iniciar la conversación."
                ),
            )
            self._write(f"{error.format_for_cli()}\n")
            return

        self.history.append(ChatMessage("user", text))
        self._write("\nNox> ")
        try:
            answer = self.provider.chat(self.history, on_token=self._write_token)
        except KeyboardInterrupt:
            self.history.pop()
            self._write("\nRespuesta cancelada.\n")
            return
        except NoxError as error:
            self.history.pop()
            self._write(f"\n{error.format_for_cli()}\n")
            return
        self.history.append(ChatMessage("assistant", answer))
        self._write("\n\n")

    def _run_internal_command(self, command: str) -> bool:
        normalized = command.casefold()
        if normalized in {"/exit", "/salir"}:
            self._write("Sesión finalizada.\n")
            return True
        if normalized in {"/help", "/ayuda"}:
            self._write(
                "\n/help     Muestra esta ayuda\n"
                "/status   Muestra el contexto activo\n"
                "/clear    Limpia la conversación actual\n"
                "/exit     Termina Nox\n\n"
            )
            return False
        if normalized in {"/clear", "/limpiar"}:
            self._reset_history()
            self._write("Conversación limpiada.\n")
            return False
        if normalized in {"/status", "/estado"}:
            self._print_status()
            return False
        self._write(f"Comando desconocido: {command}. Usá /help.\n")
        return False

    def _create_provider(
        self,
        configuration: EffectiveConfiguration,
    ) -> ModelProvider | None:
        try:
            return ProviderFactory.create(configuration)
        except NoxError as error:
            if error.code == ErrorCode.MODEL_NOT_CONFIGURED:
                return None
            raise

    def _reset_history(self) -> None:
        status = StatusService.collect(self.start, nox_version=self.nox_version)
        project = status["project"]
        assert isinstance(project, dict)
        prompt = (
            "Sos Nox, el agente local del usuario. "
            f"Trabajás en el proyecto {project.get('name')} ubicado en "
            f"{project.get('root')}. Tu contexto es {project.get('role')}. "
            "Esta versión solo tiene conversación: no afirmes haber ejecutado "
            "herramientas ni modificado archivos. Respondé de forma clara."
        )
        self.history = [ChatMessage("system", prompt)]

    def _print_banner(self) -> None:
        status = StatusService.collect(self.start, nox_version=self.nox_version)
        project = status["project"]
        assert isinstance(project, dict)
        model = self.provider.model if self.provider else "no configurado"
        provider = self.provider.name if self.provider else "no configurado"
        self._write(
            f"Nox {self.nox_version}\n"
            f"Proyecto: {project.get('name')}\n"
            f"Contexto: {str(project.get('role')).upper()}\n"
            f"Proveedor: {provider}\n"
            f"Modelo: {model}\n"
            "Escribí /help para ver los comandos de la sesión.\n\n"
        )

    def _print_status(self) -> None:
        status = StatusService.collect(self.start, nox_version=self.nox_version)
        project = status["project"]
        assert isinstance(project, dict)
        self._write(
            f"\nProyecto: {project.get('name')}\n"
            f"Raíz: {project.get('root')}\n"
            f"Contexto: {str(project.get('role')).upper()}\n"
            f"Estado: {project.get('health')}\n"
            f"Proveedor: {self.provider.name if self.provider else 'no configurado'}\n"
            f"Modelo: {self.provider.model if self.provider else 'no configurado'}\n\n"
        )

    def _read_line(self, prompt: str) -> str | None:
        self._write(prompt)
        line = self.input.readline()
        return None if line == "" else line

    def _write_token(self, token: str) -> None:
        self._write(token, flush=True)

    def _write(self, text: str, *, flush: bool = True) -> None:
        self.output.write(text)
        if flush:
            self.output.flush()
