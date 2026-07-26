"""Sesión conversacional interactiva de Nox."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import ChatMessage, ModelProvider, ProviderFactory
from nox_agent.runtime.startup import SessionStartup
from nox_agent.runtime.status import StatusService
from nox_agent.tools import ConsoleMenu

USER_PROMPT = "You> "
NOX_PROMPT = "Nox> "
THINKING_PROMPT = f"{NOX_PROMPT}Pensando..."


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
        if self.require_tty and (
            not self.input.isatty() or not self.output.isatty()
        ):
            raise NoxErrorFactory.create(ErrorCode.SESSION_TERMINAL_REQUIRED)

        configuration = SessionStartup(
            self.start,
            nox_version=self.nox_version,
            menu=ConsoleMenu(stream=self.output),
        ).prepare()
        if configuration is None:
            return 0

        self.provider = ProviderFactory.create(configuration)
        self._reset_history()
        self._print_banner()

        while True:
            try:
                text = self._read_line(USER_PROMPT)
            except KeyboardInterrupt:
                self._write("\nEntrada cancelada. Usá /exit para salir.\n")
                continue
            if text is None:
                self._write("\nSesión finalizada.\n")
                return 0

            text = text.strip()
            if not text:
                continue
            # La barra inicial es la única frontera entre Nox y el modelo.
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
                    "Usá `nox engines status`, `nox models install <nombre>` "
                    "y `nox models use <nombre> --scope global`."
                ),
            )
            self._write(f"{error.format_for_cli()}\n")
            return

        self.history.append(ChatMessage("user", text))
        answer_started = False
        pending_tokens: list[str] = []

        def show_token(token: str) -> None:
            nonlocal answer_started
            if not token:
                return
            if not answer_started:
                pending_tokens.append(token)
                if not any(part.strip() for part in pending_tokens):
                    return
                self._replace_thinking(NOX_PROMPT)
                answer_started = True
                self._write_token("".join(pending_tokens))
                pending_tokens.clear()
                return
            self._write_token(token)

        self._write(f"\n{THINKING_PROMPT}")
        try:
            answer = self.provider.chat(self.history, on_token=show_token)
        except KeyboardInterrupt:
            self.history.pop()
            self._finish_interrupted_response(
                "Respuesta cancelada.",
                answer_started=answer_started,
            )
            return
        except NoxError as error:
            self.history.pop()
            self._finish_interrupted_response(
                error.format_for_cli(),
                answer_started=answer_started,
            )
            return
        except Exception:
            if answer_started:
                self._write("\n")
            else:
                self._replace_thinking("")
            raise
        if not answer_started:
            self._replace_thinking(f"{NOX_PROMPT}{answer}")
        self.history.append(ChatMessage("assistant", answer))
        self._write("\n\n")

    def _replace_thinking(self, replacement: str) -> None:
        self._write(f"\r{' ' * len(THINKING_PROMPT)}\r{replacement}")

    def _finish_interrupted_response(
        self,
        message: str,
        *,
        answer_started: bool,
    ) -> None:
        shown = f"{NOX_PROMPT}{message}"
        if answer_started:
            self._write(f"\n\n{shown}\n\n")
        else:
            self._replace_thinking(shown)
            self._write("\n\n")

    def _run_internal_command(self, command: str) -> bool:
        normalized = command.casefold()
        if normalized in {"/exit", "/salir"}:
            self._write("Sesión finalizada.\n")
            return True
        if normalized in {"/help", "/ayuda"}:
            self._write(
                "\n/help o /ayuda       Muestra esta ayuda\n"
                "/status o /estado    Muestra el contexto activo\n"
                "/clear o /limpiar    Limpia la conversación actual\n"
                "/exit o /salir       Termina Nox\n\n"
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
