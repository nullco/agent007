"""Centralized terminal escape and control sequence constants.

This module contains both standard ANSI/CSI sequences and the terminal-
specific control sequences used by the TUI (DEC private modes, OSC/APC
sequences, Kitty protocol helpers, and related regexes).
"""
from __future__ import annotations

import re


class EscapeCodes:
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

    # ── Terminal protocol extensions ──────────────────────────────────
    SYNC_START = "\x1b[?2026h"
    SYNC_END = "\x1b[?2026l"

    BRACKETED_PASTE_ON = "\x1b[?2004h"
    BRACKETED_PASTE_OFF = "\x1b[?2004l"
    PASTE_START = "\x1b[200~"
    PASTE_END = "\x1b[201~"

    KITTY_QUERY = "\x1b[?u"
    KITTY_ENABLE = "\x1b[>7u"
    KITTY_DISABLE = "\x1b[<u"

    MODIFY_OTHER_KEYS_ON = "\x1b[>4;2m"
    MODIFY_OTHER_KEYS_OFF = "\x1b[>4;0m"

    CELL_SIZE_QUERY = "\x1b[16t"
    CELL_SIZE_RESPONSE_RE = re.compile(r"\x1b\[6;(\d+);(\d+)t")
    CELL_SIZE_PARTIAL_RE = re.compile(r"\x1b(\[6?;?[\d;]*)?$")

    HYPERLINK_RESET = "\x1b]8;;\x07"
    OSC133_ZONE_START = "\x1b]133;A\x07"
    OSC133_ZONE_END = "\x1b]133;B\x07"
    OSC133_ZONE_FINAL = "\x1b]133;C\x07"
    CURSOR_MARKER = "\x1b_pi:c\x07"

    @staticmethod
    def set_title(title: str) -> str:
        return f"\x1b]0;{title}\x07"

    # ── Composite helpers ──────────────────────────────────────────────
    SEGMENT_RESET = RESET + HYPERLINK_RESET

    # ── Truecolor helpers ──────────────────────────────────────────────
    @staticmethod
    def fg_rgb(r: int, g: int, b: int) -> str:
        return f"\x1b[38;2;{r};{g};{b}m"

    @staticmethod
    def bg_rgb(r: int, g: int, b: int) -> str:
        return f"\x1b[48;2;{r};{g};{b}m"
