"""Auditoría del ciclo de vida de comandos directos del CLI."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from nox_agent.audit.recorder import AuditRecorder
from nox_agent.logs import NoxLogs

logger = NoxLogs.get_logger("audit.command")


class CommandAuditSession:
    """Registra un comando sin mezclar persistencia con el punto de entrada."""

    def __init__(
        self,
        start: Path,
        *,
        nox_version: str,
        command: str | None,
        arguments: Namespace,
    ) -> None:
        self.command = command
        self.recorder = AuditRecorder(
            start,
            execution_mode="command",
            session_metadata={
                "session_type": "cli",
                "command": command,
                "nox_version": nox_version,
            },
        )
        self.recorder.audit(
            "command.started",
            metadata={"command": command},
            full={
                "arguments": {
                    key: value
                    for key, value in vars(arguments).items()
                    if key not in {"show_version", "show_status"}
                },
            },
        )

    def complete(self, exit_code: int) -> None:
        self._finish(outcome="success", exit_code=exit_code)

    def fail(
        self,
        *,
        outcome: str,
        exit_code: int,
        error_code: str,
    ) -> None:
        """Preserva el error original aunque falle su evento de cierre."""

        try:
            self._finish(
                outcome=outcome,
                exit_code=exit_code,
                error_code=error_code,
            )
        except Exception:
            logger.exception(
                "No se pudo cerrar la auditoría del comando fallido"
            )

    def _finish(
        self,
        *,
        outcome: str,
        exit_code: int,
        error_code: str | None = None,
    ) -> None:
        metadata: dict[str, object] = {
            "outcome": outcome,
            "exit_code": exit_code,
        }
        if error_code is not None:
            metadata["error_code"] = error_code
        self.recorder.audit("command.completed", metadata=metadata)
        self.recorder.close(outcome=outcome, metadata=metadata)
