"""Flujo natural y estado temporal de una conversación de Nox."""

from __future__ import annotations

import time
from typing import TextIO

from nox_agent.context import ProjectContextSnapshot
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import ChatMessage, ModelProvider
from nox_agent.runtime.intent import (
    IntentClassifier,
    IntentDecision,
    RequestRelation,
)
from nox_agent.runtime.observability import ReplObservability
from nox_agent.runtime.turn_observation import TurnObservation
from nox_agent.tools import TerminalActivity

NOX_PROMPT = "Nox> "
MAX_PENDING_CLARIFICATIONS = 2
CLARIFICATION_LIMIT_NOTICE = (
    "No pude precisar el pedido después de dos aclaraciones. "
    "Cerré esta solicitud para evitar un ciclo. "
    "Escribí un pedido nuevo y completo para continuar."
)


class ConversationRuntime:
    """Clasifica, responde y conserva el historial volátil del REPL."""

    def __init__(
        self,
        provider: ModelProvider,
        context: ProjectContextSnapshot,
        observability: ReplObservability,
        output_writer: TextIO,
    ) -> None:
        self.provider: ModelProvider
        self.context: ProjectContextSnapshot
        self.observability: ReplObservability
        self.output: TextIO
        self.intent_classifier: IntentClassifier
        self.pending_request: str | None = None
        self.pending_clarifications: list[str] = []
        self.history: list[ChatMessage] = []
        self.reset(provider, context, observability, output_writer)

    def reset(
        self,
        provider: ModelProvider,
        context: ProjectContextSnapshot,
        observability: ReplObservability,
        output_writer: TextIO,
    ) -> None:
        self.provider = provider
        self.context = context
        self.observability = observability
        self.output = output_writer
        self.intent_classifier = IntentClassifier(provider)
        self.pending_request = None
        self.pending_clarifications = []
        prompt = (
            "Sos Nox, el agente local del usuario. "
            "Esta versión carga contexto explícito e identifica intenciones, "
            "pero todavía no ejecuta herramientas: no afirmes haber inspeccionado "
            "archivos no incluidos en el contexto, ejecutado comandos ni "
            "modificado el sistema. Respondé de forma clara.\n\n"
            f"{context.for_model()}"
        )
        self.history = [ChatMessage("system", prompt)]

    def respond(
        self,
        text: str,
        *,
        transcript_text: str | None = None,
    ) -> None:
        turn = self.observability.begin_turn(
            text if transcript_text is None else transcript_text
        )
        self._write("\n")
        with TerminalActivity(
            self.output,
            prefix=NOX_PROMPT,
            phase="Entendiendo tu pedido",
        ) as activity:
            self._respond_with_activity(text, activity, turn)

    def _respond_with_activity(
        self,
        text: str,
        activity: TerminalActivity,
        turn: TurnObservation,
    ) -> None:
        answer_started = False
        pending_tokens: list[str] = []
        streamed_tokens: list[str] = []
        response_started_at: float | None = None
        first_content_ms: int | None = None

        def show_token(token: str) -> None:
            nonlocal answer_started, first_content_ms
            if not token:
                return
            streamed_tokens.append(token)
            if not answer_started:
                pending_tokens.append(token)
                if not any(part.strip() for part in pending_tokens):
                    return
                if response_started_at is not None:
                    first_content_ms = _elapsed_ms(response_started_at)
                activity.finish(NOX_PROMPT)
                answer_started = True
                self._write("".join(pending_tokens))
                pending_tokens.clear()
                return
            self._write(token)

        pending_request = self.pending_request
        previous_clarifications = list(self.pending_clarifications)
        classification_started_at = time.monotonic()
        try:
            decision = self.intent_classifier.classify(
                text,
                self.context,
                history=self.history,
                pending_request=pending_request,
                previous_clarifications=previous_clarifications,
            )
        except KeyboardInterrupt:
            turn.cancelled(
                "classification",
                "Respuesta cancelada.",
                classification_ms=_elapsed_ms(classification_started_at),
            )
            self._finish_interrupted_response(
                "Respuesta cancelada.",
                answer_started=False,
                activity=activity,
            )
            return
        except NoxError as error:
            notice = error.format_for_cli()
            turn.failed(
                "classification",
                str(error.code),
                notice,
                classification_ms=_elapsed_ms(classification_started_at),
            )
            self._finish_interrupted_response(
                notice,
                answer_started=False,
                activity=activity,
            )
            return
        except Exception:
            turn.failed(
                "classification",
                str(ErrorCode.UNKNOWN_CRITICAL),
                NoxErrorFactory.create(
                    ErrorCode.UNKNOWN_CRITICAL,
                ).format_for_cli(),
                classification_ms=_elapsed_ms(classification_started_at),
            )
            raise

        turn.classified(
            decision.kind.value,
            decision.confidence.value,
            decision.objective,
            _elapsed_ms(classification_started_at),
            request_relation=decision.request_relation.value,
        )

        pending_clarifications = previous_clarifications
        if decision.request_relation == RequestRelation.NEW_REQUEST:
            self._clear_pending_request()
            pending_clarifications = []
        elif self.pending_request is not None:
            pending_clarifications = [*pending_clarifications, text]

        if decision.needs_clarification:
            notice = self._clarification_notice(
                text,
                pending_clarifications,
            )
            turn.clarification(notice)
            activity.finish(f"{NOX_PROMPT}{notice}")
            self._write("\n\n")
            return

        classified_text = self._classification_text(
            text,
            pending_clarifications,
        )
        if self.pending_request is not None:
            self.pending_clarifications = pending_clarifications
        self.history.append(ChatMessage("user", classified_text))
        messages = self._messages_for_response(decision)
        activity.set_phase("Preparando la respuesta")
        response_started_at = time.monotonic()
        try:
            answer = self.provider.chat(messages, on_token=show_token)
        except KeyboardInterrupt:
            self.history.pop()
            turn.cancelled(
                "response",
                "Respuesta cancelada.",
                _partial_answer(streamed_tokens),
                response_ms=_elapsed_ms(response_started_at),
                first_content_ms=first_content_ms,
            )
            self._finish_interrupted_response(
                "Respuesta cancelada.",
                answer_started=answer_started,
                activity=activity,
            )
            return
        except NoxError as error:
            self.history.pop()
            notice = error.format_for_cli()
            turn.failed(
                "response",
                str(error.code),
                notice,
                _partial_answer(streamed_tokens),
                response_ms=_elapsed_ms(response_started_at),
                first_content_ms=first_content_ms,
            )
            self._finish_interrupted_response(
                notice,
                answer_started=answer_started,
                activity=activity,
            )
            return
        except Exception:
            self.history.pop()
            turn.failed(
                "response",
                str(ErrorCode.UNKNOWN_CRITICAL),
                NoxErrorFactory.create(
                    ErrorCode.UNKNOWN_CRITICAL,
                ).format_for_cli(),
                _partial_answer(streamed_tokens),
                response_ms=_elapsed_ms(response_started_at),
                first_content_ms=first_content_ms,
            )
            if answer_started:
                self._write("\n")
            raise

        response_ms = _elapsed_ms(response_started_at)
        if not answer_started:
            first_content_ms = response_ms
            activity.finish(f"{NOX_PROMPT}{answer}")
        turn.completed(
            answer,
            response_ms,
            first_content_ms if first_content_ms is not None else response_ms,
        )
        self.history.append(ChatMessage("assistant", answer))
        self._clear_pending_request()
        self._write("\n\n")

    def _clarification_notice(
        self,
        text: str,
        pending_clarifications: list[str],
    ) -> str:
        if (
            self.pending_request is not None
            and len(pending_clarifications) >= MAX_PENDING_CLARIFICATIONS
        ):
            self._clear_pending_request()
            return CLARIFICATION_LIMIT_NOTICE
        self._remember_clarification(text, pending_clarifications)
        return IntentDecision.question()

    def _remember_clarification(
        self,
        text: str,
        pending_clarifications: list[str],
    ) -> None:
        if self.pending_request is None:
            self.pending_request = text
            self.pending_clarifications = []
        else:
            self.pending_clarifications = pending_clarifications

    def _clear_pending_request(self) -> None:
        self.pending_request = None
        self.pending_clarifications = []

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

    def _finish_interrupted_response(
        self,
        message: str,
        *,
        answer_started: bool,
        activity: TerminalActivity,
    ) -> None:
        shown = f"{NOX_PROMPT}{message}"
        if answer_started:
            self._write(f"\n\n{shown}\n\n")
        else:
            activity.finish(shown)
            self._write("\n\n")

    def _write(self, text: str) -> None:
        self.output.write(text)
        self.output.flush()


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1000))


def _partial_answer(tokens: list[str]) -> str | None:
    answer = "".join(tokens)
    return answer if answer.strip() else None
