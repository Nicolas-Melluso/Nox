"""Sesión conversacional interactiva de Nox."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from nox_agent.context import ProjectContextService, ProjectContextSnapshot
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import ChatMessage, ModelProvider, ProviderFactory
from nox_agent.project import ProjectContext
from nox_agent.registry import context_role, load_registry
from nox_agent.runtime.intent import IntentClassifier, IntentDecision
from nox_agent.runtime.startup import SessionStartup
from nox_agent.runtime.status import StatusService
from nox_agent.tools import ConsoleMenu

USER_PROMPT = "You> "
NOX_PROMPT = "Nox> "
THINKING_PROMPT = f"{NOX_PROMPT}Pensando..."
MAX_PENDING_CLARIFICATIONS = 4


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
        self.project: ProjectContext | None = None
        self.context: ProjectContextSnapshot | None = None
        self.intent_classifier: IntentClassifier | None = None
        self.configuration_values: dict[str, str] = {}
        self.pending_request: str | None = None
        self.pending_clarifications: list[str] = []
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

        assert configuration.project is not None
        self.project = configuration.project
        self.configuration_values = {
            key: value.value for key, value in configuration.values.items()
        }
        self.provider = ProviderFactory.create(configuration)
        self.intent_classifier = IntentClassifier(self.provider)
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
        if (
            self.provider is None
            or self.context is None
            or self.intent_classifier is None
        ):
            error = NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_CONFIGURED,
                detail=(
                    "Usá `nox engines status`, `nox models install <nombre>` "
                    "y `nox models use <nombre> --scope global`."
                ),
            )
            self._write(f"{error.format_for_cli()}\n")
            return

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
        pending_clarifications = list(self.pending_clarifications)
        if self.pending_request is not None:
            pending_clarifications.append(text)
            pending_clarifications = pending_clarifications[
                -MAX_PENDING_CLARIFICATIONS:
            ]
        classified_text = self._classification_text(
            text,
            pending_clarifications,
        )
        try:
            decision = self.intent_classifier.classify(
                classified_text,
                self.context,
                history=self.history,
            )
        except KeyboardInterrupt:
            self._finish_interrupted_response(
                "Respuesta cancelada.",
                answer_started=False,
            )
            return
        except NoxError as error:
            self._finish_interrupted_response(
                error.format_for_cli(),
                answer_started=False,
            )
            return
        except Exception:
            self._replace_thinking("")
            raise

        if decision.needs_clarification:
            if self.pending_request is None:
                self.pending_request = text
                self.pending_clarifications = []
            else:
                self.pending_clarifications = pending_clarifications
            self._replace_thinking(f"{NOX_PROMPT}{decision.question()}")
            self._write("\n\n")
            return

        if self.pending_request is not None:
            self.pending_clarifications = pending_clarifications
        self.history.append(ChatMessage("user", classified_text))
        messages = self._messages_for_response(decision)
        try:
            answer = self.provider.chat(messages, on_token=show_token)
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
            self.history.pop()
            if answer_started:
                self._write("\n")
            else:
                self._replace_thinking("")
            raise
        if not answer_started:
            self._replace_thinking(f"{NOX_PROMPT}{answer}")
        self.history.append(ChatMessage("assistant", answer))
        self.pending_request = None
        self.pending_clarifications = []
        self._write("\n\n")

    def _messages_for_response(
        self,
        decision: IntentDecision,
    ) -> list[ChatMessage]:
        messages = list(self.history)
        if messages and messages[0].role == "system":
            messages[0] = ChatMessage(
                "system",
                f"{messages[0].content}\n\n{decision.response_guidance()}",
            )
        return messages

    def _classification_text(
        self,
        text: str,
        clarifications: list[str],
    ) -> str:
        if self.pending_request is None:
            return text
        sections = [f"Pedido original:\n{self.pending_request}"]
        sections.extend(
            f"Aclaración {index}:\n{clarification}"
            for index, clarification in enumerate(clarifications, start=1)
        )
        return "\n\n".join(sections)

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
        self._reload_context()
        assert self.context is not None
        self.pending_request = None
        self.pending_clarifications = []
        prompt = (
            "Sos Nox, el agente local del usuario. "
            "Esta versión carga contexto explícito e identifica intenciones, "
            "pero todavía no ejecuta herramientas: no afirmes haber inspeccionado "
            "archivos no incluidos en el contexto, ejecutado comandos ni "
            "modificado el sistema. Respondé de forma clara.\n\n"
            f"{self.context.for_model()}"
        )
        self.history = [ChatMessage("system", prompt)]

    def _reload_context(self) -> None:
        if self.project is None:
            raise NoxErrorFactory.create(ErrorCode.SESSION_PROJECT_REQUIRED)
        registry = load_registry()
        role = context_role(self.project, registry)
        self.context = ProjectContextService.load(
            self.project,
            role=role,
            configuration=self.configuration_values,
        )

    def _print_banner(self) -> None:
        assert self.context is not None
        model = self.provider.model if self.provider else "no configurado"
        provider = self.provider.name if self.provider else "no configurado"
        context_hint = (
            ""
            if self.context.sources
            else "Contexto del proyecto: no configurado (ejecutá nox init)\n"
        )
        self._write(
            f"Nox {self.nox_version}\n"
            f"Proyecto: {self.context.project_name}\n"
            f"Contexto: {self.context.role.upper()}\n"
            f"Fuentes de contexto: {len(self.context.sources)}\n"
            f"{context_hint}"
            f"Proveedor: {provider}\n"
            f"Modelo: {model}\n"
            "Escribí /help para ver los comandos de la sesión.\n\n"
        )

    def _print_status(self) -> None:
        status = StatusService.collect(self.start, nox_version=self.nox_version)
        project = status["project"]
        assert isinstance(project, dict)
        project_context = project.get("context")
        source_count = (
            project_context.get("source_count")
            if isinstance(project_context, dict)
            else 0
        )
        self._write(
            f"\nProyecto: {project.get('name')}\n"
            f"Raíz: {project.get('root')}\n"
            f"Contexto: {str(project.get('role')).upper()}\n"
            f"Fuentes de contexto: {source_count}\n"
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
