"""Ciclo auditable de una interacción conversacional."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import NoReturn
from uuid import uuid4

from nox_agent.audit import AuditRecorder

MonotonicClock = Callable[[], float]
UserTranscript = Callable[[str, str], None]
AssistantTranscript = Callable[[str, str, str, str | None], None]


class TurnObservation:
    """Registra un turno y permite un solo resultado terminal."""

    def __init__(
        self,
        recorder: AuditRecorder,
        user_text: str,
        *,
        monotonic: MonotonicClock = time.monotonic,
        user_transcript: UserTranscript,
        assistant_transcript: AssistantTranscript,
    ) -> None:
        self.recorder = recorder
        self.interaction_id = str(uuid4())
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._user_transcript = user_transcript
        self._assistant_transcript = assistant_transcript
        self._finished = False
        self._classified = False
        self._lock = threading.RLock()

        self.recorder.audit(
            "turn.started",
            interaction_id=self.interaction_id,
            metadata={"state": "started"},
            activity={"input_length": len(user_text)},
        )
        self._user_transcript(self.interaction_id, user_text)

    def classified(
        self,
        kind: str,
        confidence: str,
        objective: str,
        duration_ms: int,
        *,
        request_relation: str = "none",
    ) -> None:
        with self._lock:
            if self._finished or self._classified:
                return
            self._classified = True
        duration = _validate_duration(duration_ms, "duration_ms")
        self.recorder.audit(
            "intent.classified",
            interaction_id=self.interaction_id,
            metadata={
                "kind": kind,
                "request_relation": request_relation,
            },
            activity={"confidence": confidence},
            full={"objective": objective},
            duration_ms=duration,
        )
        self.recorder.metric(
            "intent.classification",
            interaction_id=self.interaction_id,
            metadata={
                "kind": kind,
                "outcome": "success",
                "request_relation": request_relation,
            },
            duration_ms=duration,
        )

    def clarification(self, question: str) -> None:
        total_ms = self._begin_final()
        if total_ms is None:
            return
        self._assistant_transcript(
            self.interaction_id,
            question,
            "clarification",
            None,
        )
        self._total_metric("clarification", total_ms)
        self.recorder.audit(
            "turn.clarification",
            interaction_id=self.interaction_id,
            metadata={"outcome": "clarification"},
            activity={"question_length": len(question)},
            duration_ms=total_ms,
        )

    def completed(
        self,
        answer: str,
        response_ms: int,
        first_content_ms: int,
    ) -> None:
        total_ms = self._begin_final()
        if total_ms is None:
            return
        self._assistant_transcript(
            self.interaction_id,
            answer,
            "complete",
            None,
        )
        self._response_metrics(
            "success",
            response_ms=response_ms,
            first_content_ms=first_content_ms,
        )
        self._total_metric("success", total_ms)
        self.recorder.audit(
            "turn.completed",
            interaction_id=self.interaction_id,
            metadata={"outcome": "success"},
            activity={"response_length": len(answer)},
            duration_ms=total_ms,
        )

    def cancelled(
        self,
        stage: str,
        notice: str,
        partial_answer: str | None = None,
        *,
        classification_ms: int | None = None,
        response_ms: int | None = None,
        first_content_ms: int | None = None,
    ) -> None:
        total_ms = self._begin_final()
        if total_ms is None:
            return
        self._partial_transcript(partial_answer, notice, outcome="cancelled")
        self._classification_metric("cancelled", classification_ms)
        self._response_metrics(
            "cancelled",
            response_ms=response_ms,
            first_content_ms=first_content_ms,
        )
        self._total_metric("cancelled", total_ms)
        self.recorder.audit(
            "turn.cancelled",
            interaction_id=self.interaction_id,
            metadata={"outcome": "cancelled"},
            activity={
                "stage": stage,
                "partial_response": partial_answer is not None,
            },
            duration_ms=total_ms,
        )

    def failed(
        self,
        stage: str,
        error_code: str,
        notice: str,
        partial_answer: str | None = None,
        *,
        classification_ms: int | None = None,
        response_ms: int | None = None,
        first_content_ms: int | None = None,
    ) -> None:
        total_ms = self._begin_final()
        if total_ms is None:
            return
        self._partial_transcript(partial_answer, notice, outcome="error")
        self._classification_metric("error", classification_ms)
        self._response_metrics(
            "error",
            response_ms=response_ms,
            first_content_ms=first_content_ms,
        )
        self._total_metric("error", total_ms)
        self.recorder.audit(
            "turn.failed",
            interaction_id=self.interaction_id,
            metadata={
                "outcome": "error",
                "error_code": error_code,
            },
            activity={
                "stage": stage,
                "partial_response": partial_answer is not None,
            },
            duration_ms=total_ms,
        )

    def _partial_transcript(
        self,
        partial_answer: str | None,
        notice: str,
        *,
        outcome: str,
    ) -> None:
        content = notice if partial_answer is None else partial_answer
        status = (
            outcome
            if partial_answer is None
            else f"partial_{outcome}"
        )
        self._assistant_transcript(
            self.interaction_id,
            content,
            status,
            notice if partial_answer is not None else None,
        )

    def _classification_metric(
        self,
        outcome: str,
        duration_ms: int | None,
    ) -> None:
        if duration_ms is None:
            return
        self.recorder.metric(
            "intent.classification",
            interaction_id=self.interaction_id,
            metadata={"outcome": outcome},
            duration_ms=_validate_duration(
                duration_ms,
                "classification_ms",
            ),
        )

    def _response_metrics(
        self,
        outcome: str,
        *,
        response_ms: int | None,
        first_content_ms: int | None,
    ) -> None:
        if response_ms is not None:
            self.recorder.metric(
                "model.response",
                interaction_id=self.interaction_id,
                metadata={"outcome": outcome},
                duration_ms=_validate_duration(response_ms, "response_ms"),
            )
        if first_content_ms is not None:
            self.recorder.metric(
                "model.first_content",
                interaction_id=self.interaction_id,
                metadata={"outcome": outcome},
                duration_ms=_validate_duration(
                    first_content_ms,
                    "first_content_ms",
                ),
            )

    def _total_metric(self, outcome: str, duration_ms: int) -> None:
        self.recorder.metric(
            "turn.total",
            interaction_id=self.interaction_id,
            metadata={"outcome": outcome},
            duration_ms=duration_ms,
        )

    def _begin_final(self) -> int | None:
        with self._lock:
            if self._finished:
                return None
            self._finished = True
            return _elapsed_ms(self._started_at, self._monotonic)


def _elapsed_ms(started_at: float, monotonic: MonotonicClock) -> int:
    return max(0, round((monotonic() - started_at) * 1000))


def _validate_duration(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _invalid_duration(field)
    return value


def _invalid_duration(field: str) -> NoReturn:
    raise ValueError(f"{field} debe ser un entero no negativo.")
