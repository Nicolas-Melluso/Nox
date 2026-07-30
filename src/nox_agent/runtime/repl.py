"""Sesión conversacional interactiva de Nox."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from nox_agent.audit import AuditRecorder
from nox_agent.context import ProjectContextService, ProjectContextSnapshot
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.logs import NoxLogs
from nox_agent.models import ModelProvider, ProviderFactory
from nox_agent.project import ProjectContext
from nox_agent.registry import context_role, load_registry
from nox_agent.runtime.conversation import ConversationRuntime, NOX_PROMPT
from nox_agent.runtime.observability import ReplObservability
from nox_agent.runtime.startup import SessionStartup
from nox_agent.runtime.status import StatusService
from nox_agent.tools import ConsoleMenu, TerminalActivity

USER_PROMPT = "You> "
LOGGER = NoxLogs.get_logger("runtime.repl")


class ReplSession:
    """Prepara y coordina una sesión interactiva de Nox."""

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
        self.configuration_values: dict[str, str] = {}
        self.observability: ReplObservability | None = None
        self.conversation: ConversationRuntime | None = None

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
        self.observability = ReplObservability(
            AuditRecorder(
                self.start,
                execution_mode="interactive",
                session_metadata={
                    "session_type": "repl",
                    "nox_version": self.nox_version,
                    "project_id": self.project.manifest.project_id,
                    "project_name": self.project.manifest.name,
                    "project_root": self.project.root,
                    "provider": self.provider.name,
                    "model": self.provider.model,
                },
            )
        )

        outcome = "success"
        exit_code = 0
        error_code: str | None = None
        try:
            if not self._prepare_provider():
                outcome = "cancelled"
                exit_code = 130
                return exit_code
            self._reset_history()
            assert self.context is not None
            self.observability.session_ready(
                self.context.role,
                len(self.context.sources),
            )
            self._print_banner()
            return self._run_loop()
        except KeyboardInterrupt:
            outcome = "cancelled"
            exit_code = 130
            error_code = str(ErrorCode.OPERATION_CANCELLED)
            raise
        except NoxError as error:
            outcome = "error"
            exit_code = 1
            error_code = str(error.code)
            raise
        except Exception:
            outcome = "error"
            exit_code = 2
            error_code = str(ErrorCode.UNKNOWN_CRITICAL)
            raise
        finally:
            metadata: dict[str, object] = {"exit_code": exit_code}
            if error_code is not None:
                metadata["error_code"] = error_code
            self._close_observability(outcome, metadata)

    def _run_loop(self) -> int:
        assert self.observability is not None
        assert self.conversation is not None
        while True:
            try:
                text = self._read_line(USER_PROMPT)
            except KeyboardInterrupt:
                notice = "Entrada cancelada. Usá /exit para salir."
                self.observability.input_cancelled(notice)
                self._write(f"\n{notice}\n")
                continue
            if text is None:
                self.observability.recorder.audit(
                    "input.closed",
                    metadata={"outcome": "session_ended"},
                )
                self._write("\nSesión finalizada.\n")
                return 0

            entered_text = text.rstrip("\r\n")
            normalized = entered_text.strip()
            if not normalized:
                continue
            # La barra inicial es la única frontera entre Nox y el modelo.
            if normalized.startswith("/"):
                if self._run_internal_command(
                    normalized,
                    transcript_text=entered_text,
                ):
                    return 0
                continue
            self.conversation.respond(
                normalized,
                transcript_text=entered_text,
            )

    def _prepare_provider(self) -> bool:
        assert self.provider is not None
        assert self.observability is not None
        self._write("\n")
        with TerminalActivity(
            self.output,
            prefix=NOX_PROMPT,
            phase="Preparando el modelo local",
        ) as activity:
            try:
                self.observability.provider_prepare(self.provider.prepare)
            except KeyboardInterrupt:
                activity.finish(f"{NOX_PROMPT}Preparación cancelada.")
                self._write("\n")
                return False
        return True

    def _run_internal_command(
        self,
        command: str,
        *,
        transcript_text: str,
    ) -> bool:
        assert self.observability is not None
        interaction_id = self.observability.begin_internal_command(
            transcript_text
        )
        try:
            normalized = command.casefold()
            if normalized in {"/exit", "/salir"}:
                self._write_internal_response(
                    interaction_id,
                    "Sesión finalizada.\n",
                )
                return True
            if normalized in {"/help", "/ayuda"}:
                self._write_internal_response(
                    interaction_id,
                    "\n/help o /ayuda       Muestra esta ayuda\n"
                    "/status o /estado    Muestra el contexto activo\n"
                    "/clear o /limpiar    Limpia la conversación actual\n"
                    "/exit o /salir       Termina Nox\n\n",
                )
                return False
            if normalized in {"/clear", "/limpiar"}:
                self._reset_history()
                self._write_internal_response(
                    interaction_id,
                    "Conversación limpiada.\n",
                )
                return False
            if normalized in {"/status", "/estado"}:
                self._write_internal_response(
                    interaction_id,
                    self._status_text(),
                )
                return False
            self._write_internal_response(
                interaction_id,
                f"Comando desconocido: {command}. Usá /help.\n",
                outcome="unknown",
            )
            return False
        except NoxError as error:
            self.observability.fail_internal_command(
                interaction_id,
                str(error.code),
                error_type=type(error).__name__,
            )
            raise
        except Exception as error:
            self.observability.fail_internal_command(
                interaction_id,
                str(ErrorCode.UNKNOWN_CRITICAL),
                error_type=type(error).__name__,
            )
            raise

    def _write_internal_response(
        self,
        interaction_id: str,
        response: str,
        *,
        outcome: str = "completed",
    ) -> None:
        assert self.observability is not None
        self.observability.complete_internal_command(
            interaction_id,
            response,
            outcome=outcome,
        )
        self._write(response)

    def _close_observability(
        self,
        outcome: str,
        metadata: dict[str, object],
    ) -> None:
        assert self.observability is not None
        try:
            self.observability.close(
                outcome=outcome,
                metadata=metadata,
            )
        except Exception:
            if outcome == "success":
                raise
            LOGGER.exception(
                "No se pudo cerrar la auditoría de una sesión con resultado %s.",
                outcome,
            )

    def _reset_history(self) -> None:
        self._reload_context()
        assert self.provider is not None
        assert self.context is not None
        assert self.observability is not None
        if self.conversation is None:
            self.conversation = ConversationRuntime(
                self.provider,
                self.context,
                self.observability,
                self.output,
            )
            return
        self.conversation.reset(
            self.provider,
            self.context,
            self.observability,
            self.output,
        )

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

    def _status_text(self) -> str:
        status = StatusService.collect(self.start, nox_version=self.nox_version)
        project = status["project"]
        assert isinstance(project, dict)
        project_context = project.get("context")
        source_count = (
            project_context.get("source_count")
            if isinstance(project_context, dict)
            else 0
        )
        return (
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

    def _write(self, text: str, *, flush: bool = True) -> None:
        self.output.write(text)
        if flush:
            self.output.flush()
