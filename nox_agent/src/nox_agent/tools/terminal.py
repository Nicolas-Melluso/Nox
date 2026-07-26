"""Control seguro de la pantalla de consola en Windows."""

from __future__ import annotations

import ctypes
import msvcrt
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from typing import TextIO

CLEAR_SCREEN = "\x1b[2J\x1b[H"
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


class _Coord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SmallRect(ctypes.Structure):
    _fields_ = [
        ("Left", ctypes.c_short),
        ("Top", ctypes.c_short),
        ("Right", ctypes.c_short),
        ("Bottom", ctypes.c_short),
    ]


class _ConsoleScreenBufferInfo(ctypes.Structure):
    _fields_ = [
        ("dwSize", _Coord),
        ("dwCursorPosition", _Coord),
        ("wAttributes", wintypes.WORD),
        ("srWindow", _SmallRect),
        ("dwMaximumWindowSize", _Coord),
    ]


class _ConsoleCursorInfo(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("bVisible", wintypes.BOOL)]


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

_KERNEL32.GetConsoleMode.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
]
_KERNEL32.GetConsoleMode.restype = wintypes.BOOL
_KERNEL32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_KERNEL32.SetConsoleMode.restype = wintypes.BOOL
_KERNEL32.GetConsoleScreenBufferInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_ConsoleScreenBufferInfo),
]
_KERNEL32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
_KERNEL32.FillConsoleOutputCharacterW.argtypes = [
    wintypes.HANDLE,
    wintypes.WCHAR,
    wintypes.DWORD,
    _Coord,
    ctypes.POINTER(wintypes.DWORD),
]
_KERNEL32.FillConsoleOutputCharacterW.restype = wintypes.BOOL
_KERNEL32.FillConsoleOutputAttribute.argtypes = [
    wintypes.HANDLE,
    wintypes.WORD,
    wintypes.DWORD,
    _Coord,
    ctypes.POINTER(wintypes.DWORD),
]
_KERNEL32.FillConsoleOutputAttribute.restype = wintypes.BOOL
_KERNEL32.SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, _Coord]
_KERNEL32.SetConsoleCursorPosition.restype = wintypes.BOOL
_KERNEL32.GetConsoleCursorInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_ConsoleCursorInfo),
]
_KERNEL32.GetConsoleCursorInfo.restype = wintypes.BOOL
_KERNEL32.SetConsoleCursorInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_ConsoleCursorInfo),
]
_KERNEL32.SetConsoleCursorInfo.restype = wintypes.BOOL


class TerminalDisplay:
    """Limpia la pantalla y controla el cursor sin filtrar ANSI crudo."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._handle = self._console_handle(stream)

    def clear(self) -> None:
        self.stream.flush()
        if self._handle is not None:
            if self._clear_with_virtual_terminal():
                return
            if self._clear_with_windows_api():
                return

        # Un TextIO interactivo no respaldado por una consola Win32 no debe
        # recibir secuencias que podría mostrar literalmente.
        self.stream.write("\n")
        self.stream.flush()

    @contextmanager
    def hidden_cursor(self) -> Iterator[None]:
        if self._handle is None:
            yield
            return

        original = _ConsoleCursorInfo()
        if not _KERNEL32.GetConsoleCursorInfo(
            self._handle,
            ctypes.byref(original),
        ):
            yield
            return

        hidden = _ConsoleCursorInfo()
        hidden.dwSize = original.dwSize
        hidden.bVisible = False
        changed = bool(
            _KERNEL32.SetConsoleCursorInfo(
                self._handle,
                ctypes.byref(hidden),
            )
        )
        try:
            yield
        finally:
            if changed:
                _KERNEL32.SetConsoleCursorInfo(
                    self._handle,
                    ctypes.byref(original),
                )

    @staticmethod
    def _console_handle(stream: TextIO) -> int | None:
        try:
            handle = msvcrt.get_osfhandle(stream.fileno())
        except (AttributeError, OSError, ValueError):
            return None
        mode = wintypes.DWORD()
        if handle == -1 or not _KERNEL32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None
        return handle

    def _clear_with_virtual_terminal(self) -> bool:
        assert self._handle is not None
        original = wintypes.DWORD()
        if not _KERNEL32.GetConsoleMode(
            self._handle,
            ctypes.byref(original),
        ):
            return False

        enabled = (
            original.value
            | ENABLE_PROCESSED_OUTPUT
            | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )
        if not _KERNEL32.SetConsoleMode(self._handle, enabled):
            return False
        try:
            self.stream.write(CLEAR_SCREEN)
            self.stream.flush()
            return True
        finally:
            _KERNEL32.SetConsoleMode(self._handle, original.value)

    def _clear_with_windows_api(self) -> bool:
        assert self._handle is not None
        information = _ConsoleScreenBufferInfo()
        if not _KERNEL32.GetConsoleScreenBufferInfo(
            self._handle,
            ctypes.byref(information),
        ):
            return False

        cells = int(information.dwSize.X) * int(information.dwSize.Y)
        if cells <= 0:
            return False
        origin = _Coord(0, 0)
        written = wintypes.DWORD()
        characters_cleared = bool(
            _KERNEL32.FillConsoleOutputCharacterW(
                self._handle,
                " ",
                cells,
                origin,
                ctypes.byref(written),
            )
        )
        attributes_cleared = bool(
            _KERNEL32.FillConsoleOutputAttribute(
                self._handle,
                information.wAttributes,
                cells,
                origin,
                ctypes.byref(written),
            )
        )
        cursor_moved = bool(
            _KERNEL32.SetConsoleCursorPosition(self._handle, origin)
        )
        return characters_cleared and attributes_cleared and cursor_moved
