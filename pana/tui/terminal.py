"""Raw terminal I/O layer.

Provides a Protocol for terminal interaction and a concrete ProcessTerminal
implementation using sys.stdin/stdout, tty/termios, and asyncio.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import sys
import termios
import tty
from collections.abc import Awaitable, Callable
from typing import Protocol

from pana.tui.escape_codes import EscapeCodes
from pana.tui.protocols.kitty.keyboard import KittyKeyboardProtocolController
from pana.tui.stdin_buffer import StdinBuffer


class Terminal(Protocol):
    """Minimal terminal I/O interface."""

    def start(self, on_resize: Callable[[], None]) -> None: ...

    async def run(self, on_input: Callable[[str], Awaitable[None]]) -> None: ...

    def stop(self) -> None: ...

    def write(self, data: str) -> None: ...

    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...

    def move_by(self, lines: int) -> None: ...

    def hide_cursor(self) -> None: ...

    def show_cursor(self) -> None: ...

    def clear_line(self) -> None: ...

    def clear_from_cursor(self) -> None: ...

    def clear_screen(self) -> None: ...

    def set_title(self, title: str) -> None: ...

    async def drain_input(self, max_ms: float = 1000, idle_ms: float = 50) -> None: ...


class ProcessTerminal:
    """Terminal backed by the hosting process's stdin/stdout.

    Environment variables:
        PANA_TUI_WRITE_LOG  – path to append every written byte to (debug).
    """

    def __init__(self) -> None:
        self._original_attrs: list[int | list[bytes | int]] | None = None
        self._original_flags: int | None = None
        self._on_input: Callable[[str], None] | None = None
        self._on_resize: Callable[[], None] | None = None
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._sigwinch_registered: bool = False
        self._stdin_fd: int | None = None
        self._stdin_buffer: StdinBuffer | None = None
        self._write_log_path: str = os.environ.get("PANA_TUI_WRITE_LOG", "")
        self._keyboard_protocol = KittyKeyboardProtocolController(self.write)

    def start(self, on_resize: Callable[[], None]) -> None:
        self._on_resize = on_resize

        if not sys.stdin.isatty():
            return

        fd = sys.stdin.fileno()
        self._stdin_fd = fd

        self._original_attrs = termios.tcgetattr(fd)
        self._original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)

        tty.setraw(fd)
        self.write(EscapeCodes.BRACKETED_PASTE_ON)

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGWINCH, self._handle_sigwinch)
        self._sigwinch_registered = True

        self._setup_stdin_buffer()
        self._keyboard_protocol.start()

        self._on_input = self._input_queue.put_nowait
        loop.add_reader(fd, self._read_stdin)

    def stop(self) -> None:
        fd = self._stdin_fd
        if fd is not None:
            self._keyboard_protocol.stop()
            self.write(EscapeCodes.BRACKETED_PASTE_OFF)

            if self._stdin_buffer is not None:
                self._stdin_buffer.destroy()
                self._stdin_buffer = None

            try:
                loop = asyncio.get_running_loop()
                loop.remove_reader(fd)
            except RuntimeError:
                pass

            self._input_queue.put_nowait(None)

            if self._original_attrs is not None:
                termios.tcsetattr(fd, termios.TCSAFLUSH, self._original_attrs)
                self._original_attrs = None

            if self._original_flags is not None:
                fcntl.fcntl(fd, fcntl.F_SETFL, self._original_flags)
                self._original_flags = None

            self._stdin_fd = None

        if self._sigwinch_registered:
            try:
                loop = asyncio.get_running_loop()
                loop.remove_signal_handler(signal.SIGWINCH)
            except RuntimeError:
                pass
            self._sigwinch_registered = False

        self._on_input = None
        self._on_resize = None

    async def run(self, on_input: Callable[[str], Awaitable[None]]) -> None:
        """Read keystrokes from the queue and dispatch them asynchronously.

        Returns when stop() is called (which enqueues a None sentinel).
        """
        while True:
            data = await self._input_queue.get()
            if data is None:
                break
            await on_input(data)

    def write(self, data: str) -> None:
        sys.stdout.write(data)
        sys.stdout.flush()
        if self._write_log_path:
            try:
                with open(self._write_log_path, "a", encoding="utf-8") as f:
                    f.write(data)
            except OSError:
                pass

    @property
    def columns(self) -> int:
        return os.get_terminal_size().columns

    @property
    def rows(self) -> int:
        return os.get_terminal_size().lines

    def move_by(self, lines: int) -> None:
        if lines > 0:
            self.write(EscapeCodes.cursor_down(lines))
        elif lines < 0:
            self.write(EscapeCodes.cursor_up(-lines))

    def hide_cursor(self) -> None:
        self.write(EscapeCodes.HIDE_CURSOR)

    def show_cursor(self) -> None:
        self.write(EscapeCodes.SHOW_CURSOR)

    def clear_line(self) -> None:
        self.write(EscapeCodes.CLEAR_LINE)

    def clear_from_cursor(self) -> None:
        self.write(EscapeCodes.CLEAR_FROM_CURSOR)

    def clear_screen(self) -> None:
        self.write(EscapeCodes.CLEAR_SCREEN)

    def set_title(self, title: str) -> None:
        self.write(EscapeCodes.set_title(title))

    async def drain_input(self, max_ms: float = 1000, idle_ms: float = 50) -> None:
        self._keyboard_protocol.stop()

        saved_handler = self._on_input
        self._on_input = None
        last_data_time = asyncio.get_running_loop().time()

        def _on_data(_: str) -> None:
            nonlocal last_data_time
            last_data_time = asyncio.get_running_loop().time()

        if self._stdin_buffer is not None:
            prev_on_data = self._stdin_buffer.on_data
            self._stdin_buffer.on_data = _on_data
        else:
            prev_on_data = None

        try:
            end_time = asyncio.get_running_loop().time() + max_ms / 1000.0
            slice_s = min(idle_ms, 10) / 1000.0
            while True:
                now = asyncio.get_running_loop().time()
                if now >= end_time:
                    break
                if now - last_data_time >= idle_ms / 1000.0:
                    break
                await asyncio.sleep(slice_s)
        finally:
            if self._stdin_buffer is not None:
                self._stdin_buffer.on_data = prev_on_data
            self._on_input = saved_handler

    def _handle_sigwinch(self) -> None:
        if self._on_resize is not None:
            self._on_resize()

    def _read_stdin(self) -> None:
        if self._stdin_fd is None or self._on_input is None:
            return
        try:
            data = os.read(self._stdin_fd, 4096)
        except (OSError, BlockingIOError):
            return
        if data:
            text = data.decode("utf-8", errors="replace")
            if self._stdin_buffer is not None:
                self._stdin_buffer.process(text)
            else:
                self._on_input(text)

    def _setup_stdin_buffer(self) -> None:
        """Set up StdinBuffer to split batched input into individual sequences."""
        buf = StdinBuffer(timeout_ms=10)

        def _on_data(data: str) -> None:
            if self._keyboard_protocol.handle_input(data):
                return
            if self._on_input is not None:
                self._on_input(data)

        def _on_paste(content: str) -> None:
            if self._on_input is not None:
                self._on_input(EscapeCodes.PASTE_START + content + EscapeCodes.PASTE_END)

        buf.on_data = _on_data
        buf.on_paste = _on_paste
        self._stdin_buffer = buf
