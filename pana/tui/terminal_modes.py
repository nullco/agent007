"""Terminal-specific protocol modes and extensions.

These are NOT standard ANSI escape sequences.  They are DEC private modes,
OSC sequences, APC markers, and vendor-specific protocols supported by
modern terminal emulators (xterm, Kitty, iTerm2, etc.).
"""
from __future__ import annotations

import re


class TerminalModes:
    # ── Synchronized output (DEC 2026) ─────────────────────────────────
    SYNC_START = "\x1b[?2026h"
    SYNC_END = "\x1b[?2026l"

    # ── Bracketed paste mode ───────────────────────────────────────────
    BRACKETED_PASTE_ON = "\x1b[?2004h"
    BRACKETED_PASTE_OFF = "\x1b[?2004l"
    PASTE_START = "\x1b[200~"
    PASTE_END = "\x1b[201~"

    # ── Kitty keyboard protocol ────────────────────────────────────────
    KITTY_QUERY = "\x1b[?u"
    KITTY_ENABLE = "\x1b[>7u"
    KITTY_DISABLE = "\x1b[<u"

    # ── xterm modifyOtherKeys ──────────────────────────────────────────
    MODIFY_OTHER_KEYS_ON = "\x1b[>4;2m"
    MODIFY_OTHER_KEYS_OFF = "\x1b[>4;0m"

    # ── Window / terminal title (OSC 0) ────────────────────────────────
    @staticmethod
    def set_title(title: str) -> str:
        return f"\x1b]0;{title}\x07"

    # ── Cell-size query (xterm) ────────────────────────────────────────
    CELL_SIZE_QUERY = "\x1b[16t"
    CELL_SIZE_RESPONSE_RE = re.compile(r"\x1b\[6;(\d+);(\d+)t")
    CELL_SIZE_PARTIAL_RE = re.compile(r"\x1b(\[6?;?[\d;]*)?$")

    # ── OSC hyperlink reset (OSC 8) ────────────────────────────────────
    HYPERLINK_RESET = "\x1b]8;;\x07"

    # ── OSC 133 semantic zones (shell integration) ──────────────────────
    OSC133_ZONE_START = "\x1b]133;A\x07"
    OSC133_ZONE_END   = "\x1b]133;B\x07"
    OSC133_ZONE_FINAL = "\x1b]133;C\x07"

    # ── Application-level markers ─────────────────────────────────────
    CURSOR_MARKER = "\x1b_pi:c\x07"  # APC zero-width cursor position marker
