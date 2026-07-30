"""Observabilidad de sesión del REPL."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from uuid import uuid4

from nox_agent.audit import AuditRecorder
from nox_agent.errors import NoxError
from nox_agent.runtime.turn_observation import TurnObservation

MonotonicClock = Callable[[], float]


class ReplObservability:
    """Traduce la sesión del REPL a eventos sin ensuciar su flujo."""

    def __init__(
        self,
        recorder: AuditRecorder,
        *,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        self.recorder = recorder
        self._monotonic = monotonic

    def provider_prepare(self, prepare: Callable[[], None]) -> None:
        """Ejecuta y mide ``provider.prepare`` sin alterar sus excepciones."""

        started_at = self._monotonic()
        try:
            prepare()
        except KeyboardInterrupt:
            self._record_provider_prepare(
                "cancelled",
                self._elapsed_ms(started_at),
            )
            raise
        except Exception as error:
            duration_ms = self._elapsed_ms(started_at)
            metadata: dict[str, object] = {"outcome": "error"}
            if isinstance(error, NoxError):
                metadata["error_code"] = str(error.code)
            self.recorder.audit(
                "provider.prepare",
                metadata=metadata,
                activity={"error_type": type(error).__name__},
                duration_ms=duration_ms,
            )
            self.recorder.metric(
                "provider.prepare",
                metadata={"outcome": "error"},
                duration_ms=duration_ms,
            )
            raise
        self._record_provider_prepare(
            "success",
            self._elapsed_ms(started_at),
        )

    def session_ready(self, role: str, source_count: int) -> None:
        self.recorder.audit(
            "session.ready",
            metadata={"state": "ready", "role": role},
            activity={"source_count": source_count},
        )

    def input_cancelled(
        self,
        notice: str = "Entrada cancelada. Usá /exit para salir.",
    ) -> None:
        interaction_id = str(uuid4())
        self.recorder.audit(
            "input.cancelled",
            interaction_id=interaction_id,
            metadata={"outcome": "cancelled"},
            activity={"stage": "input"},
        )
        self._assistant_transcript(
            interaction_id,
            notice,
            "notice",
        )

    def internal_command(self, command: str, response: str) -> None:
        interaction_id = self.begin_internal_command(command)
        self.complete_internal_command(interaction_id, response)

    def begin_internal_command(self, command: str) -> str:
        interaction_id = str(uuid4())
        self._user_transcript(
            interaction_id,
            command,
            kind="internal_command",
        )
        self.recorder.audit(
            "internal.command.started",
            interaction_id=interaction_id,
            metadata={"state": "started"},
            activity={"command": _command_name(command)},
        )
        return interaction_id

    def complete_internal_command(
        self,
        interaction_id: str,
        response: str,
        *,
        outcome: str = "completed",
    ) -> None:
        self._assistant_transcript(
            interaction_id,
            response,
            "complete",
            kind="internal_command",
        )
        self.recorder.audit(
            "internal.command.completed",
            interaction_id=interaction_id,
            metadata={"outcome": outcome},
            activity={"response_length": len(response)},
        )

    def fail_internal_command(
        self,
        interaction_id: str,
        error_code: str,
        *,
        error_type: str | None = None,
    ) -> None:
        activity = (
            {"error_type": error_type}
            if error_type is not None
            else None
        )
        self.recorder.audit(
            "internal.command.failed",
            interaction_id=interaction_id,
            metadata={
                "outcome": "error",
                "error_code": error_code,
            },
            activity=activity,
        )

    def begin_turn(self, user_text: str) -> TurnObservation:
        return TurnObservation(
            self.recorder,
            user_text,
            monotonic=self._monotonic,
            user_transcript=self._user_transcript,
            assistant_transcript=self._assistant_transcript,
        )

    def close(
        self,
        *,
        outcome: str = "success",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.recorder.close(outcome=outcome, metadata=metadata)

    def _record_provider_prepare(
        self,
        outcome: str,
        duration_ms: int,
    ) -> None:
        self.recorder.audit(
            "provider.prepare",
            metadata={"outcome": outcome},
            duration_ms=duration_ms,
        )
        self.recorder.metric(
            "provider.prepare",
            metadata={"outcome": outcome},
            duration_ms=duration_ms,
        )

    def _elapsed_ms(self, started_at: float) -> int:
        return max(
            0,
            round((self._monotonic() - started_at) * 1000),
        )

    def _user_transcript(
        self,
        interaction_id: str,
        content: str,
        *,
        kind: str = "conversation",
    ) -> None:
        self.recorder.transcript(
            "message.user",
            interaction_id=interaction_id,
            metadata={"role": "user", "kind": kind},
            full={"content": content},
        )

    def _assistant_transcript(
        self,
        interaction_id: str,
        content: str,
        status: str,
        notice: str | None = None,
        *,
        kind: str = "conversation",
    ) -> None:
        full: dict[str, object] = {"content": content}
        if notice is not None:
            full["notice"] = notice
        self.recorder.transcript(
            "message.assistant",
            interaction_id=interaction_id,
            metadata={
                "role": "assistant",
                "kind": kind,
                "status": status,
            },
            full=full,
        )


def _command_name(command: str) -> str:
    stripped = command.strip()
    return stripped.split(maxsplit=1)[0].casefold() if stripped else "(empty)"
