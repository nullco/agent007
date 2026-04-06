"""Centralized ANSI escape code constants.

Only standard ANSI escape sequences live here: SGR text attributes,
cursor movement / visibility, and line / screen clearing.

For terminal-specific protocol modes (bracketed paste, Kitty keyboard,
synchronized output, OSC sequences, etc.) see ``terminal_modes.py``.
"""
from __future__ import annotations

from pana.tui.terminal_modes import TerminalModes


class ANSI:
    # ── Full reset ──────────────────────────────────────────────────────
    RESET = "\x1b[0m"

    # ── SGR text attributes (on / off) ─────────────────────────────────
    BOLD_ON = "\x1b[1m"
    BOLD_OFF = "\x1b[22m"
    DIM_ON = "\x1b[2m"
    ITALIC_ON = "\x1b[3m"
    ITALIC_OFF = "\x1b[23m"
    UNDERLINE_ON = "\x1b[4m"
    UNDERLINE_OFF = "\x1b[24m"
    BLINK_ON = "\x1b[5m"
    INVERSE_ON = "\x1b[7m"
    INVERSE_OFF = "\x1b[27m"
    HIDDEN_ON = "\x1b[8m"
    STRIKETHROUGH_ON = "\x1b[9m"
    STRIKETHROUGH_OFF = "\x1b[29m"

    # ── Foreground / background reset ──────────────────────────────────
    FG_RESET = "\x1b[39m"
    BG_RESET = "\x1b[49m"

    # ── Cursor movement ────────────────────────────────────────────────
    @staticmethod
    def cursor_up(n: int) -> str:
        return f"\x1b[{n}A"

    @staticmethod
    def cursor_down(n: int) -> str:
        return f"\x1b[{n}B"

    @staticmethod
    def cursor_forward(n: int) -> str:
        return f"\x1b[{n}C"

    @staticmethod
    def cursor_back(n: int) -> str:
        return f"\x1b[{n}D"

    @staticmethod
    def cursor_column(col: int) -> str:
        """Move to absolute column (1-indexed)."""
        return f"\x1b[{col}G"

    # ── Cursor visibility ──────────────────────────────────────────────
    HIDE_CURSOR = "\x1b[?25l"
    SHOW_CURSOR = "\x1b[?25h"

    # ── Line / screen clearing ─────────────────────────────────────────
    CLEAR_LINE = "\x1b[K"
    CLEAR_FULL_LINE = "\x1b[2K"
    CLEAR_FROM_CURSOR = "\x1b[J"
    CLEAR_SCREEN = "\x1b[2J\x1b[H"
    CLEAR_SCROLLBACK = "\x1b[3J"

    # ── Composite helpers ──────────────────────────────────────────────
    SEGMENT_RESET = RESET + TerminalModes.HYPERLINK_RESET

    # ── Truecolor helpers ──────────────────────────────────────────────
    @staticmethod
    def fg_rgb(r: int, g: int, b: int) -> str:
        return f"\x1b[38;2;{r};{g};{b}m"

    @staticmethod
    def bg_rgb(r: int, g: int, b: int) -> str:
        return f"\x1b[48;2;{r};{g};{b}m"
