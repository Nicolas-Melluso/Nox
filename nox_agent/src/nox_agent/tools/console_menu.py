"""Menú de consola reutilizable para interfaces interactivas de Nox."""

from __future__ import annotations

import msvcrt
import sys
from dataclasses import dataclass
from typing import TextIO

from nox_agent.errors import ErrorCode, NoxErrorFactory

CLEAR_SCREEN = "\x1b[2J\x1b[H"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"


@dataclass(frozen=True)
class MenuItem:
    label: str
    value: str
    enabled: bool = True
    annotation: str | None = None


class ConsoleMenu:
    """Permite navegar opciones con flechas, Enter y Escape."""

    def __init__(self, *, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout

    def select(
        self,
        title: str,
        items: list[MenuItem],
        *,
        description: str | None = None,
    ) -> MenuItem | None:
        if not sys.stdin.isatty() or not self.stream.isatty():
            raise NoxErrorFactory.create(
                ErrorCode.INTERACTIVE_TERMINAL_REQUIRED,
                detail="Usá la forma directa del comando para automatizaciones.",
            )
        if not items:
            return None

        selected = self._first_enabled(items)
        self.stream.write(HIDE_CURSOR)
        self.stream.flush()
        try:
            while True:
                self._render(title, items, selected, description)
                key = self._read_key()
                if key == "escape":
                    return None
                if key == "up":
                    selected = self._move(items, selected, -1)
                elif key == "down":
                    selected = self._move(items, selected, 1)
                elif key == "enter" and items[selected].enabled:
                    return items[selected]
        finally:
            self.stream.write(SHOW_CURSOR)
            self.stream.flush()

    def message(self, title: str, lines: list[str]) -> None:
        if not sys.stdin.isatty() or not self.stream.isatty():
            return
        self.stream.write(CLEAR_SCREEN)
        self.stream.write(f"{title}\n\n")
        for line in lines:
            self.stream.write(f"{line}\n")
        self.stream.write("\nPresioná Enter o Escape para volver.")
        self.stream.flush()
        while self._read_key() not in {"enter", "escape"}:
            pass

    def clear(self) -> None:
        self.stream.write(CLEAR_SCREEN)
        self.stream.flush()

    def _render(
        self,
        title: str,
        items: list[MenuItem],
        selected: int,
        description: str | None,
    ) -> None:
        self.stream.write(CLEAR_SCREEN)
        self.stream.write(f"{title}\n")
        if description:
            self.stream.write(f"{description}\n")
        self.stream.write("\n")
        for index, item in enumerate(items):
            marker = ">" if index == selected else " "
            annotation = f"  [{item.annotation}]" if item.annotation else ""
            self.stream.write(f"{marker} {item.label}{annotation}\n")
        self.stream.write("\n↑/↓ navegar · Enter seleccionar · Escape volver")
        self.stream.flush()

    @staticmethod
    def _read_key() -> str:
        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            extended = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(extended, "other")
        return {"\r": "enter", "\x1b": "escape"}.get(key, "other")

    @staticmethod
    def _first_enabled(items: list[MenuItem]) -> int:
        for index, item in enumerate(items):
            if item.enabled:
                return index
        return 0

    @staticmethod
    def _move(items: list[MenuItem], current: int, direction: int) -> int:
        candidate = current
        for _ in items:
            candidate = (candidate + direction) % len(items)
            if items[candidate].enabled:
                return candidate
        return current
