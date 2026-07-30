"""Confirmación uniforme para operaciones con efectos externos."""

import sys
from typing import Never

from nox_agent.errors import ErrorCode, NoxErrorFactory


class Confirmation:
    """Exige una autorización interactiva o el indicador --yes."""

    ACCEPTED = {"s", "si", "sí", "y", "yes"}

    @classmethod
    def require(
        cls,
        confirmed: bool,
        description: str,
        *,
        allow_prompt: bool = True,
    ) -> None:
        if confirmed:
            return
        if not allow_prompt or not sys.stdin.isatty():
            cls._required("Repetí el comando con --yes para confirmar.")
        try:
            print(
                f"{description}. ¿Continuar? [s/N]: ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            answer = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            cls._required("La operación fue cancelada por el usuario.")
        if answer == "":
            cls._required("La operación fue cancelada por el usuario.")
        if answer.strip().casefold() not in cls.ACCEPTED:
            cls._required("La operación fue cancelada por el usuario.")

    @staticmethod
    def _required(detail: str) -> Never:
        raise NoxErrorFactory.create(
            ErrorCode.ACTION_CONFIRMATION_REQUIRED,
            detail=detail,
        )
