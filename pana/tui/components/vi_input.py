"""Vim-mode single-line text input component.

A full-featured modal editor wrapping the existing Input component with
vim keybindings, modes, operators, motions, text objects, registers,
marks, visual selection, and a repeat (dot) command.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum, auto

import grapheme

from pana.tui.components.input import PROMPT_WIDTH
from pana.tui.escape_codes import EscapeCodes
from pana.tui.keybindings import get_editor_keybindings
from pana.tui.keys import decode_kitty_printable
from pana.tui.utils import (
    is_punctuation_char,
    is_whitespace_char,
    visible_width,
)

# ── helpers ────────────────────────────────────────────────────────────


def _graphemes(text: str) -> list[str]:
    return list(grapheme.graphemes(text))


def _toggle_case(text: str) -> str:
    result: list[str] = []
    for ch in text:
        if ch.islower():
            result.append(ch.upper())
        elif ch.isupper():
            result.append(ch.lower())
        else:
            result.append(ch)
    return "".join(result)


MATCHING_PAIRS: dict[str, str] = {
    "(": ")", ")": "(",
    "[": "]", "]": "[",
    "{": "}", "}": "{",
    "<": ">", ">": "<",
}


# ── enums ──────────────────────────────────────────────────────────────


class ViMode(Enum):
    NORMAL = auto()
    INSERT = auto()
    VISUAL = auto()
    VISUAL_LINE = auto()
    OPERATOR_PENDING = auto()
    REPLACE_CHAR = auto()


class InsertVariant(Enum):
    PLAIN = auto()  # i
    APPEND = auto()  # a
    LINE_START = auto()  # I
    LINE_END = auto()  # A


class Operator(Enum):
    DELETE = auto()
    YANK = auto()
    CHANGE = auto()
    TOGGLE_CASE = auto()


# ── data structures ────────────────────────────────────────────────────


@dataclass
class _Change:
    """Snapshot for repeat (dot)."""

    operator: Operator | None = None
    motion_range: tuple[int, int] | None = None  # (start, end) byte offsets
    motion_text: str | None = None
    register_name: str | None = None

    # Insert-mode batch
    is_insert_batch: bool = False
    insert_start_cursor: int = 0
    insert_text: str = ""  # the text that was inserted


# ── ViModeInput ────────────────────────────────────────────────────────


class ViModeInput:
    """Full-featured single-line vim-mode text input.

    Wraps the underlying Input component and adds a modal editing layer.

    Parameters:
        on_submit: Called when Enter is pressed in normal mode, or
                   when the underlying submit key is pressed.
        on_escape: Called when Escape is pressed and we are in normal
                   mode with no pending operation.
        initial_value: Starting text.
        vi_mode_only: If True (default), start in NORMAL mode.
                      If False, start in INSERT mode as a regular input.
    """

    def __init__(
        self,
        *,
        on_submit: Callable[[str], Awaitable[None]] | None = None,
        on_escape: Callable[[], None] | None = None,
        initial_value: str = "",
        vi_mode_only: bool = True,
    ) -> None:
        from pana.tui.components.input import Input

        self._input = Input(
            on_submit=None,  # we dispatch ourselves
            on_escape=None,
            initial_value=initial_value,
        )
        self._vi_mode_only = vi_mode_only
        self._user_on_submit = on_submit
        self._user_on_escape = on_escape

        # ── mode state ──
        self._mode: ViMode = ViMode.NORMAL if vi_mode_only else ViMode.INSERT
        self._insert_variant: InsertVariant = InsertVariant.PLAIN
        self._visual_anchor: int = 0
        self._op: Operator | None = None
        self._count_str: str = ""
        self._op_text_object_type: str | None = None  # e.g. "i", "a"
        self._op_register: str | None = None
        self._pending_g: bool = False
        # Separated pending state for pure motions and mark jumps
        # (entered via OP-PENDING mode but without an operator).
        # Values: "f", "F", "t", "T", "mark_jump", "search"
        self._pending_motion_kind: str | None = None
        self._search_old_value: str = ""

        # ── registers ──
        self._named_registers: dict[str, str] = {}
        self._unnamed_register: str = ""

        # ── last change (for . repeat) ──
        self._last_change: _Change | None = None
        self._insert_start_cursor: int = 0

        # ── search ──
        self._last_search: str | None = None
        self._last_search_forward: bool = True

        # ── marks ──
        self._marks: dict[str, int] = {}

        # ── find/till ──
        self._last_find_char: str | None = None
        self._last_find_forward: bool = True

    # ── properties ─────────────────────────────────────────────────────

    @property
    def value(self) -> str:
        return self._input.value

    @value.setter
    def value(self, v: str) -> None:
        self._input.value = v

    @property
    def cursor(self) -> int:
        return self._input.cursor

    @cursor.setter
    def cursor(self, c: int) -> None:
        self._input.cursor = max(0, min(c, len(self._input.value)))

    @property
    def focused(self) -> bool:
        return self._input.focused

    @focused.setter
    def focused(self, f: bool) -> None:
        self._input.focused = f

    @property
    def mode(self) -> ViMode:
        return self._mode

    # ── public API ─────────────────────────────────────────────────────

    def invalidate(self) -> None:
        self._input.invalidate()

    def render(self, width: int) -> list[str]:
        if not self._vi_mode_only:
            return self._input.render(width)
        lines = self._input.render(width)
        mode_indicator = self._mode_indicator()
        pad_w = max(0, width - PROMPT_WIDTH - visible_width(mode_indicator))
        lines.append(f"{' ' * PROMPT_WIDTH}{' ' * pad_w}{mode_indicator}")
        return lines

    def get_value(self) -> str:
        return self._input.get_value()

    def set_value(self, value: str, *, cursor: int | None = None) -> None:
        self._input.set_value(value, cursor=cursor)

    def clear(self) -> None:
        self._input.clear()

    # ── mode indicator ─────────────────────────────────────────────────

    def _mode_indicator(self) -> str:
        inv = EscapeCodes.INVERSE_ON
        off = EscapeCodes.INVERSE_OFF
        if self._mode == ViMode.NORMAL:
            name = " NORMAL "
        elif self._mode == ViMode.INSERT:
            name = " INSERT "
        elif self._mode == ViMode.VISUAL:
            name = " VISUAL "
        elif self._mode == ViMode.VISUAL_LINE:
            name = " VISUAL LINE "
        elif self._mode == ViMode.OPERATOR_PENDING:
            name = " OP-PENDING "
        elif self._mode == ViMode.REPLACE_CHAR:
            name = " REPLACE "
        else:
            name = " ??? "
        return f"{inv}{name}{off}"

    # ── input dispatch ─────────────────────────────────────────────────

    async def handle_input(self, data: str) -> None:
        if not self._vi_mode_only:
            await self._input.handle_input(data)
            return

        kb = get_editor_keybindings()

        if self._mode == ViMode.INSERT:
            await self._handle_insert(data, kb)
            return

        if self._mode == ViMode.REPLACE_CHAR:
            await self._handle_replace_char(data, kb)
            return

        if self._mode == ViMode.OPERATOR_PENDING:
            await self._handle_operator_pending(data, kb)
            return

        if self._mode in (ViMode.VISUAL, ViMode.VISUAL_LINE):
            await self._handle_visual(data, kb)
            return

        # NORMAL mode
        await self._handle_normal(data, kb)

    # ── normal mode ────────────────────────────────────────────────────

    async def _handle_normal(self, data: str, kb) -> None:
        # Check bound submit
        if kb.matches(data, "tui.input.submit"):
            if self._user_on_submit:
                await self._user_on_submit(self._input.value)
            return

        # Escape — pass to caller if no pending state
        if kb.matches(data, "tui.select.cancel"):
            if self._count_str or self._pending_g or self._op_register:
                self._clear_sequence()
                return
            if self._user_on_escape:
                self._user_on_escape()
            return

        # Decode character
        ch = self._decode_char(data)
        if ch is not None:
            await self._dispatch_normal_char(ch)
            return

        # Arrow key equivalents in normal mode
        if kb.matches(data, "tui.editor.cursorLeft"):
            await self._dispatch_normal_char("h")
        elif kb.matches(data, "tui.editor.cursorRight"):
            await self._dispatch_normal_char("l")
        elif kb.matches(data, "tui.editor.cursorWordLeft"):
            await self._dispatch_normal_char("b")
        elif kb.matches(data, "tui.editor.cursorWordRight"):
            await self._dispatch_normal_char("w")
        elif kb.matches(data, "tui.editor.cursorLineStart"):
            await self._dispatch_normal_char("0")
        elif kb.matches(data, "tui.editor.cursorLineEnd"):
            await self._dispatch_normal_char("$")
        elif kb.matches(data, "tui.editor.deleteCharForward"):
            await self._dispatch_normal_char("x")
        elif kb.matches(data, "tui.editor.undo"):
            await self._undo_normal(1)
        elif data == "\r":
            if self._user_on_submit:
                await self._user_on_submit(self._input.value)

    async def _dispatch_normal_char(self, ch: str) -> None:
        """Route a single character in normal mode."""
        # ── count accumulation ──
        if ch.isdigit() and ch != "0":
            if self._count_str or ch not in ("0", "1"):
                self._count_str += ch
                return
            # ch == "0" but no count_str yet → cursorLineStart below

        count = int(self._count_str) if self._count_str else 1

        # ── g-prefix ──
        if self._pending_g:
            await self._handle_g_sequence(ch, count)
            return

        # ── register prefix ──
        if ch == '"' and self._op_register is None and not self._count_str:
            self._op_register = '"'
            return
        if self._op_register == '"':
            self._op_register = ch
            return

        # ── mark set ──
        if ch == "m" and not self._count_str:
            self._pending_motion_kind = "set_mark"
            self._mode = ViMode.OPERATOR_PENDING
            self._op = None
            return

        # ── operator pending start ──
        if ch in ("d", "y", "c") and not self._count_str:
            self._op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE}[ch]
            self._mode = ViMode.OPERATOR_PENDING
            return

        # ── execute command ──
        await self._execute_normal_command(count, ch)

    async def _execute_normal_command(self, count: int, ch: str) -> None:
        cmd = ch

        # Motions
        if cmd == "h":
            self._move_left_n(count)
        elif cmd == "l":
            self._move_right_n(count)
        elif cmd == "w":
            self._move_word_forward_n(count)
        elif cmd == "b":
            self._move_word_backward_n(count)
        elif cmd == "e":
            self._move_word_end_forward_n(count)
        elif cmd == "0":
            self._move_cursor_to(0)
        elif cmd == "$":
            self._move_cursor_to(len(self._input.value))
        elif cmd == "^":
            self._move_cursor_to_first_non_whitespace()

        # Find/till
        elif cmd == "f":
            self._start_pending_find("f")
        elif cmd == "F":
            self._start_pending_find("F")
        elif cmd == "t":
            self._start_pending_find("t")
        elif cmd == "T":
            self._start_pending_find("T")
        elif cmd == ";":
            self._repeat_find(True, count)
        elif cmd == ",":
            self._repeat_find(False, count)

        # Jump matching pair
        elif cmd == "%":
            self._jump_match_pair()

        # Editing
        elif cmd == "x":
            self._delete_chars_forward_n(count)
        elif cmd == "X":
            self._delete_chars_backward_n(count)
        elif cmd == "D":
            self._op_delete_range(self.cursor, len(self._input.value))
        elif cmd == "C":
            self._op_change_range(self.cursor, len(self._input.value))
        elif cmd == "s":
            end = min(self.cursor + count, len(self._input.value))
            self._op_change_range(self.cursor, end)
        elif cmd == "S":
            self._op_change_range(0, len(self._input.value))
        elif cmd == "~":
            end = min(self.cursor + count, len(self._input.value))
            self._op_toggle_case_range(self.cursor, end)
        elif cmd == "p":
            for _ in range(count):
                self._paste_after()
        elif cmd == "P":
            for _ in range(count):
                self._paste_before()
        elif cmd == "r":
            self._mode = ViMode.REPLACE_CHAR

        # Operators (start operator-pending)
        elif cmd in ("d", "y", "c"):
            self._op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE}[cmd]
            self._mode = ViMode.OPERATOR_PENDING

        # g prefix
        elif cmd == "g":
            self._pending_g = True

        # Visual mode
        elif cmd == "v":
            self._mode = ViMode.VISUAL
            self._visual_anchor = self.cursor
        elif cmd == "V":
            self._mode = ViMode.VISUAL_LINE
            self._visual_anchor = 0

        # Insert mode entry
        elif cmd == "i":
            self._enter_insert(InsertVariant.PLAIN)
        elif cmd == "a":
            self._enter_insert(InsertVariant.APPEND)
        elif cmd == "I":
            self._enter_insert(InsertVariant.LINE_START)
        elif cmd == "A":
            self._enter_insert(InsertVariant.LINE_END)

        # Undo
        elif cmd == "u":
            self._undo_normal(count)

        # Repeat
        elif cmd == ".":
            for _ in range(count):
                self._repeat_last_change()

        # Search
        elif cmd == "/":
            self._start_pending_search(True)
        elif cmd == "?":
            self._start_pending_search(False)
        elif cmd == "n":
            self._repeat_search(True, count)
        elif cmd == "N":
            self._repeat_search(False, count)

        # Marks: jump to mark
        elif cmd == "'":
            self._start_pending_mark_jump()
        elif cmd == "`":
            self._start_pending_mark_jump()

        self._clear_sequence()

    async def _handle_g_sequence(self, ch: str, count: int) -> None:
        """Handle commands starting with 'g'."""
        self._pending_g = False
        if ch == "g":
            self._move_cursor_to(0)  # gg
        elif ch == "~":
            end = min(self.cursor + count, len(self._input.value))
            self._op_toggle_case_range(self.cursor, end)
        elif ch == "u":
            self._op_change_case_range(True, self.cursor, len(self._input.value))
        elif ch == "U":
            self._op_change_case_range(False, self.cursor, len(self._input.value))
        elif ch == "j":
            pass  # single-line no-op
        elif ch == "k":
            pass
        self._clear_sequence()

    # ── operator-pending mode ──────────────────────────────────────────

    async def _handle_operator_pending(self, data: str, kb) -> None:
        if kb.matches(data, "tui.select.cancel"):
            self._clear_sequence()
            self._mode = ViMode.NORMAL
            return

        ch = self._decode_char(data)
        if ch is not None:
            if ch.isdigit() and ch != "0":
                self._count_str += ch
                return

            # ── Pure motion pending (no operator) ──
            if self._op is None:
                await self._handle_pure_motion(ch)
                return

            # ── Operator pending: complete the operator ──
            await self._finish_operator(ch)
            return

    async def _handle_pure_motion(self, ch: str) -> None:
        """Handle a character completing a pure motion (f/F/t/T/mark)."""
        kind = self._pending_motion_kind
        count = int(self._count_str) if self._count_str else 1

        if kind == "set_mark":
            self._set_mark(ch)
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        if kind == "mark_jump":
            self._jump_to_mark(ch)
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        if kind in ("f", "F", "t", "T"):
            forward = kind in ("f", "t")
            for _ in range(count):
                if kind in ("f", "F"):
                    pos = self._find_char_position(ch, forward)
                    if pos is not None:
                        self._move_cursor_to(pos)
                    else:
                        break
                else:  # t, T
                    pos = self._till_char_position(ch, forward)
                    if pos is not None:
                        self._move_cursor_to(pos)
                    else:
                        break
            self._last_find_char = ch
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        # Unknown pending motion — cancel
        self._mode = ViMode.NORMAL
        self._clear_sequence()

    async def _finish_operator(self, ch: str) -> None:
        if self._op is None:
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        op = self._op
        count = int(self._count_str) if self._count_str else 1

        # Doubled operator → linewise
        op_char = {
            Operator.DELETE: "d",
            Operator.YANK: "y",
            Operator.CHANGE: "c",
        }.get(op)
        if ch == op_char:
            self._op_exec(op, 0, len(self._input.value))
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        # Text object start (i/a)
        if ch in ("i", "a"):
            self._op_text_object_type = ch
            return

        # After i/a, next char completes the text object
        if self._op_text_object_type:
            self._op_exec_text_object(self._op_text_object_type + ch)
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        # f/F/t/T motion (with operator)
        if ch in ("f", "F", "t", "T"):
            self._pending_motion_kind = ch
            return
        if self._pending_motion_kind in ("f", "F", "t", "T"):
            kind = self._pending_motion_kind
            forward = kind in ("f", "t")
            pos = self._find_char_position(ch, forward) if kind in ("f", "F") else self._till_char_position(ch, forward)
            if pos is not None:
                if kind in ("f", "F"):
                    end = pos + 1 if pos >= self.cursor else pos
                else:
                    end = pos + 1 if kind == "t" else pos
                start = self.cursor
                r_start = min(start, end)
                r_end = max(start, end)
                self._op_exec(op, r_start, r_end)
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        # Motion
        motion_end = self._compute_motion_end(ch, count)
        if motion_end is not None:
            start = self.cursor
            end = motion_end
            # Only e, $, l are inclusive motions in vim
            # w, b, 0, ^, h are exclusive
            inclusive = ch in ("e", "$", "l")
            if inclusive and end < len(self._input.value) and end > start:
                end += 1
            self._op_exec(op, min(start, end), max(start, end))
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        self._mode = ViMode.NORMAL
        self._clear_sequence()

    def _compute_motion_end(self, ch: str, count: int) -> int | None:
        """Compute cursor position after a motion without moving the cursor."""
        saved = self.cursor
        try:
            if ch == "h":
                for _ in range(count):
                    self._move_left()
            elif ch == "l":
                for _ in range(count):
                    self._move_right()
            elif ch == "w":
                for _ in range(count):
                    self._move_word_forward()
            elif ch == "b":
                for _ in range(count):
                    self._move_word_backward()
            elif ch == "e":
                for _ in range(count):
                    self._move_word_end_forward()
            elif ch == "0":
                self._move_cursor_to(0)
            elif ch == "$":
                self._move_cursor_to(len(self._input.value))
            elif ch == "^":
                self._move_cursor_to_first_non_whitespace()
            else:
                return None
            return self.cursor
        finally:
            self.cursor = saved

    # ── operator execution ─────────────────────────────────────────────

    def _op_exec(self, op: Operator, start: int, end: int) -> None:
        """Execute an operator on range [start, end)."""
        text = self._input.value[start:end]
        reg = self._effective_register()

        if op == Operator.DELETE:
            self._store_register(reg, text)
            self._input._push_undo()
            self._input.value = self._input.value[:start] + self._input.value[end:]
            self._move_cursor_to(start)
            self._last_change = _Change(operator=op, motion_range=(start, end), register_name=reg)

        elif op == Operator.YANK:
            self._store_register(reg, text)
            self._move_cursor_to(start)
            # Yank doesn't create a repeatable change

        elif op == Operator.CHANGE:
            self._store_register(reg, text)
            self._input._push_undo()
            self._input.value = self._input.value[:start] + self._input.value[end:]
            self._move_cursor_to(start)
            self._last_change = _Change(operator=op, motion_range=(start, end), register_name=reg)
            self._enter_insert(InsertVariant.PLAIN)

        elif op == Operator.TOGGLE_CASE:
            self._input._push_undo()
            toggled = _toggle_case(self._input.value[start:end])
            self._input.value = self._input.value[:start] + toggled + self._input.value[end:]
            self._move_cursor_to(end)
            self._last_change = _Change(operator=op, motion_range=(start, end))

    def _op_delete_range(self, start: int, end: int) -> None:
        self._op_exec(Operator.DELETE, start, end)

    def _op_change_range(self, start: int, end: int) -> None:
        self._op_exec(Operator.CHANGE, start, end)

    def _op_toggle_case_range(self, start: int, end: int) -> None:
        self._op_exec(Operator.TOGGLE_CASE, start, end)

    def _op_change_case_range(self, to_upper: bool, start: int, end: int) -> None:
        text = self._input.value[start:end]
        new_text = text.upper() if to_upper else text.lower()
        if text != new_text:
            self._input._push_undo()
            self._input.value = self._input.value[:start] + new_text + self._input.value[end:]
            self._last_change = _Change(operator=Operator.TOGGLE_CASE, motion_range=(start, end))

    # ── text objects ───────────────────────────────────────────────────

    def _op_exec_text_object(self, obj: str) -> None:
        if self._op is None:
            return
        rng = self._text_object_range(obj)
        if rng is not None:
            self._op_exec(self._op, rng[0], rng[1])

    def _text_object_range(self, obj: str) -> tuple[int, int] | None:
        """Return (start, end) for a text object, or None if not found."""
        cursor = self.cursor
        value = self._input.value

        if obj in ("iw", "aw"):
            return self._word_text_object(cursor, value, obj == "aw")

        if obj in ("iW", "aW"):
            return self._WORD_text_object(cursor, value, obj == "aW")

        # Paired delimiters: i(, a(, i[, a[, i{, a{, i<, a<, i", a", i', a'
        if len(obj) == 2 and obj[0] in ("i", "a"):
            delim = obj[1]
            if delim in ('"', "'", "`"):
                return self._quote_text_object(cursor, value, delim, obj[0] == "a")
            matching = MATCHING_PAIRS.get(delim)
            if matching is not None:
                return self._paired_text_object(cursor, value, delim, matching, obj[0] == "a")

        return None

    def _word_text_object(self, cursor: int, value: str, include_ws: bool) -> tuple[int, int] | None:
        """iw / aw text object."""
        if not value:
            return None
        start = cursor
        end = cursor

        ch_at = value[cursor] if cursor < len(value) else " "

        if is_whitespace_char(ch_at):
            # Cursor on whitespace: select whitespace + surrounding word
            while start > 0 and is_whitespace_char(value[start - 1]):
                start -= 1
            while end < len(value) and is_whitespace_char(value[end]):
                end += 1
            if include_ws:
                while start > 0 and not is_whitespace_char(value[start - 1]):
                    start -= 1
                if end < len(value) and not is_whitespace_char(value[end]):
                    while end < len(value) and not is_whitespace_char(value[end]):
                        end += 1
                    end += 1  # include trailing space for aw
            return (start, end)

        # On word character
        is_punct = is_punctuation_char(ch_at)
        while start > 0:
            prev_ch = value[start - 1]
            if is_whitespace_char(prev_ch):
                break
            if is_punctuation_char(prev_ch) != is_punct:
                break
            start -= 1
        while end < len(value):
            next_ch = value[end]
            if is_whitespace_char(next_ch):
                break
            if is_punctuation_char(next_ch) != is_punct:
                break
            end += 1

        if include_ws:
            while end < len(value) and is_whitespace_char(value[end]):
                end += 1

        return (start, end)

    def _WORD_text_object(self, cursor: int, value: str, include_ws: bool) -> tuple[int, int] | None:
        """iW / aW text object: WORD = non-whitespace."""
        if not value:
            return None
        start = cursor
        end = cursor
        ch_at = value[cursor] if cursor < len(value) else " "

        if is_whitespace_char(ch_at):
            while start > 0 and is_whitespace_char(value[start - 1]):
                start -= 1
            while end < len(value) and is_whitespace_char(value[end]):
                end += 1
            if include_ws:
                while start > 0 and not is_whitespace_char(value[start - 1]):
                    start -= 1
                while end < len(value) and not is_whitespace_char(value[end]):
                    end += 1
            return (start, end)

        while start > 0 and not is_whitespace_char(value[start - 1]):
            start -= 1
        while end < len(value) and not is_whitespace_char(value[end]):
            end += 1
        if include_ws:
            while end < len(value) and is_whitespace_char(value[end]):
                end += 1
        return (start, end)

    def _paired_text_object(
        self, cursor: int, value: str, open_delim: str, close_delim: str, include_delim: bool
    ) -> tuple[int, int] | None:
        """Text object for paired delimiters: i(, a(, i[, etc."""
        ch_at = value[cursor] if cursor < len(value) else ""

        # If on a delimiter, find the matching pair
        if ch_at == open_delim:
            end = self._find_matching_pair_forward(cursor, value, open_delim, close_delim)
            if end is None:
                return None
            start = cursor
        elif ch_at == close_delim:
            start = self._find_matching_pair_backward(cursor, value, open_delim, close_delim)
            if start is None:
                return None
            end = cursor
        else:
            # Search for enclosing pair
            end = self._find_next_close(value, cursor, open_delim, close_delim)
            if end is None:
                return None
            start = self._find_matching_pair_backward(end, value, open_delim, close_delim)
            if start is None:
                return None

        if include_delim:
            return (start, end + 1)
        else:
            return (start + 1, end)

    def _quote_text_object(
        self, cursor: int, value: str, quote: str, include_quote: bool
    ) -> tuple[int, int] | None:
        """Text object for quoted strings: i", a", i', a'."""
        # Find the enclosing quotes
        end = value.find(quote, cursor + 1 if cursor < len(value) and value[cursor] == quote else cursor)
        if end == -1:
            return None
        # Find start: the quote character before cursor, searching backwards
        search_limit = cursor if (cursor < len(value) and value[cursor] == quote) else cursor + 1
        start = value.rfind(quote, 0, search_limit)
        if start == -1:
            return None
        if include_quote:
            return (start, end + 1)
        else:
            return (start + 1, end)

    def _find_matching_pair_forward(self, pos: int, value: str, open_delim: str, close_delim: str) -> int | None:
        """Find the matching close delimiter counting nesting."""
        depth = 0
        i = pos
        while i < len(value):
            if value[i] == open_delim and not self._in_string_literal(value, i, open_delim):
                depth += 1
            elif value[i] == close_delim and not self._in_string_literal(value, i, close_delim):
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return None

    def _find_matching_pair_backward(self, pos: int, value: str, open_delim: str, close_delim: str) -> int | None:
        """Find the matching open delimiter counting nesting."""
        depth = 0
        i = pos
        while i >= 0:
            if value[i] == close_delim and not self._in_string_literal(value, i, close_delim):
                depth += 1
            elif value[i] == open_delim and not self._in_string_literal(value, i, open_delim):
                depth -= 1
                if depth == 0:
                    return i
            i -= 1
        return None

    def _find_next_close(self, value: str, cursor: int, open_delim: str, close_delim: str) -> int | None:
        """Find the first close delimiter after cursor (with nesting)."""
        depth = 0
        for i in range(cursor, len(value)):
            if value[i] == open_delim and not self._in_string_literal(value, i, open_delim):
                depth += 1
            elif value[i] == close_delim and not self._in_string_literal(value, i, close_delim):
                if depth == 0:
                    return i
                depth -= 1
        return None

    @staticmethod
    def _in_string_literal(value: str, pos: int, delim: str) -> bool:
        """Check if position is inside a string literal (escaped)."""
        count = 0
        i = pos - 1
        while i >= 0 and value[i] == "\\":
            count += 1
            i -= 1
        return count % 2 == 1

    # ── insert mode ────────────────────────────────────────────────────

    def _enter_insert(self, variant: InsertVariant) -> None:
        self._mode = ViMode.INSERT
        self._insert_variant = variant
        self._insert_start_cursor = self.cursor

        if variant == InsertVariant.APPEND:
            if self.cursor < len(self._input.value):
                self._move_right()
        elif variant == InsertVariant.LINE_START:
            self._move_cursor_to_first_non_whitespace()
        elif variant == InsertVariant.LINE_END:
            self._move_cursor_to(len(self._input.value))

        self._input._push_undo()
        self._input._typing_run = True

    async def _handle_insert(self, data: str, kb) -> None:
        # Search mode: Enter executes the search, Escape cancels
        if self._pending_motion_kind == "search":
            if kb.matches(data, "tui.select.cancel"):
                # Cancel search, restore old value
                self._input._pop_undo()
                self._pending_motion_kind = None
                self._mode = ViMode.NORMAL
                return
            if kb.matches(data, "tui.input.submit") or data == "\r":
                pattern = self._input.value
                self._input._pop_undo()  # undo the search-mode clear
                self._last_search = pattern
                self._search(pattern, self._last_search_forward)
                self._pending_motion_kind = None
                self._mode = ViMode.NORMAL
                return
            await self._input.handle_input(data)
            return

        # Regular insert mode
        if kb.matches(data, "tui.select.cancel"):
            self._exit_insert()
            return

        if kb.matches(data, "tui.input.submit"):
            if self._user_on_submit:
                await self._user_on_submit(self._input.value)
            return

        await self._input.handle_input(data)

    def _exit_insert(self) -> None:
        self._mode = ViMode.NORMAL

        # vim cursor adjustment: move left one unless at start or entered via 'a'
        if self._insert_variant == InsertVariant.PLAIN:
            if self.cursor > 0:
                self._move_left()
        elif self._insert_variant == InsertVariant.LINE_START:
            if self.cursor > 0:
                self._move_left()

        # Record insert change
        inserted = self._input.value[self._insert_start_cursor : self.cursor]
        self._last_change = _Change(
            is_insert_batch=True,
            insert_start_cursor=self._insert_start_cursor,
            insert_text=inserted,
        )

    # ── replace-char mode ──────────────────────────────────────────────

    async def _handle_replace_char(self, data: str, kb) -> None:
        if kb.matches(data, "tui.select.cancel"):
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        ch = self._decode_char(data)
        if ch is not None:
            if self.cursor < len(self._input.value):
                gs = _graphemes(self._input.value[self.cursor :])
                old_char = gs[0] if gs else ""
                self._input._push_undo()
                self._input.value = (
                    self._input.value[: self.cursor]
                    + ch
                    + self._input.value[self.cursor + len(old_char) :]
                )
                self._last_change = _Change(
                    operator=Operator.CHANGE,
                    motion_range=(self.cursor, self.cursor + len(old_char)),
                )
        self._mode = ViMode.NORMAL
        self._clear_sequence()

    # ── visual mode ────────────────────────────────────────────────────

    async def _handle_visual(self, data: str, kb) -> None:
        if kb.matches(data, "tui.select.cancel"):
            self._mode = ViMode.NORMAL
            self._clear_sequence()
            return

        if kb.matches(data, "tui.editor.cursorLeft"):
            self._move_left()
            return
        if kb.matches(data, "tui.editor.cursorRight"):
            self._move_right()
            return
        if kb.matches(data, "tui.editor.cursorLineStart"):
            self._move_cursor_to(0)
            return
        if kb.matches(data, "tui.editor.cursorLineEnd"):
            self._move_cursor_to(len(self._input.value))
            return
        if kb.matches(data, "tui.editor.cursorWordLeft"):
            self._move_word_backward()
            return
        if kb.matches(data, "tui.editor.cursorWordRight"):
            self._move_word_forward()
            return
        if kb.matches(data, "tui.input.submit"):
            if self._user_on_submit:
                await self._user_on_submit(self._input.value)
            return

        ch = self._decode_char(data)
        if ch is not None:
            if ch in ("d", "y", "c", "~"):
                op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE, "~": Operator.TOGGLE_CASE}[ch]
                start, end = self._visual_range()
                self._op_exec(op, start, end)
                self._mode = ViMode.NORMAL
                self._clear_sequence()
                return
            if ch == "v":
                self._mode = ViMode.NORMAL
                self._clear_sequence()
                return
            # Motions in visual mode
            await self._dispatch_normal_char(ch)

    def _visual_range(self) -> tuple[int, int]:
        """Return (start, end) for visual selection. End is exclusive."""
        a = self._visual_anchor
        c = self.cursor
        if self._mode == ViMode.VISUAL:
            if a <= c:
                start, end = a, c
            else:
                start, end = c, a
            # Include character under cursor
            if end < len(self._input.value):
                gs = _graphemes(self._input.value[end:])
                if gs:
                    end += len(gs[0])
            return (start, end)
        # VISUAL_LINE: entire single-line
        return (0, len(self._input.value))

    # ── find / till ────────────────────────────────────────────────────

    def _start_pending_find(self, kind: str) -> None:
        """Enter pending state waiting for a character to find/till."""
        self._pending_motion_kind = kind
        self._last_find_forward = kind in ("f", "t")
        self._mode = ViMode.OPERATOR_PENDING
        self._op = None  # no operator, just motion
        self._count_str = ""

    def _find_char_position(self, ch: str, forward: bool) -> int | None:
        """Find position of character in the appropriate direction."""
        value = self._input.value
        cursor = self.cursor
        if forward:
            idx = value.find(ch, cursor + 1)
        else:
            idx = value.rfind(ch, 0, cursor)
        if idx == -1:
            return None
        return idx

    def _till_char_position(self, ch: str, forward: bool) -> int | None:
        """Till position: like find but stop before/after character."""
        pos = self._find_char_position(ch, forward)
        if pos is None:
            return None
        if forward:
            return max(pos - 1, 0)
        else:
            return min(pos + 1, len(self._input.value))

    def _repeat_find(self, same_direction: bool, count: int) -> None:
        """Repeat last f/F/t/T with ; or ,."""
        if self._last_find_char is None:
            return
        forward = self._last_find_forward if same_direction else not self._last_find_forward
        # Use the stored pending_motion_kind to determine find vs till,
        # defaulting to find-style.
        kind = self._pending_motion_kind if self._pending_motion_kind in ("f", "F", "t", "T") else "f"

        for _ in range(count):
            if kind in ("f", "F"):
                pos = self._find_char_position(self._last_find_char, forward)
                if pos is not None:
                    self._move_cursor_to(pos)
                else:
                    break
            elif kind in ("t", "T"):
                pos = self._till_char_position(self._last_find_char, forward)
                if pos is not None:
                    self._move_cursor_to(pos)
                else:
                    break

    # ── search ─────────────────────────────────────────────────────────

    def _start_pending_search(self, forward: bool) -> None:
        """Start a search: type pattern then press Enter to execute."""
        self._last_search_forward = forward
        self._pending_motion_kind = "search"
        self._mode = ViMode.INSERT
        self._insert_variant = InsertVariant.PLAIN
        self._insert_start_cursor = 0
        # Clear the input for search pattern entry
        self._input._push_undo()
        old_value = self._input.value
        self._input.value = ""
        self._input.cursor = 0
        # Store old value to restore on cancel
        self._search_old_value = old_value

    def _repeat_search(self, same_direction: bool, count: int) -> None:
        """Repeat last search with n/N."""
        if self._last_search is None:
            return
        forward = self._last_search_forward if same_direction else not self._last_search_forward
        for _ in range(count):
            self._search(self._last_search, forward)

    def _search(self, pattern: str, forward: bool) -> None:
        """Search for pattern and move cursor."""
        value = self._input.value
        cursor = self.cursor
        if forward:
            idx = value.find(pattern, cursor + 1)
            if idx == -1:
                idx = value.find(pattern)
        else:
            start = cursor - 1 if cursor > 0 else 0
            idx = value.rfind(pattern, 0, start)
            if idx == -1:
                idx = value.rfind(pattern)
        if idx != -1:
            self._move_cursor_to(idx)

    # ── marks ──────────────────────────────────────────────────────────

    def _set_mark(self, name: str) -> None:
        """Set a mark at the current cursor position."""
        if len(name) == 1 and name.isalpha():
            self._marks[name] = self.cursor

    def _start_pending_mark_jump(self) -> None:
        """Wait for mark character to jump to."""
        self._pending_motion_kind = "mark_jump"
        self._mode = ViMode.OPERATOR_PENDING
        self._op = None
        self._count_str = ""

    def _jump_to_mark(self, name: str) -> None:
        """Jump cursor to a mark."""
        if name in self._marks:
            self._move_cursor_to(self._marks[name])

    # ── jump matching pair ─────────────────────────────────────────────

    def _jump_match_pair(self) -> None:
        """Jump to matching parenthesis/bracket/brace."""
        value = self._input.value
        if self.cursor >= len(value):
            return
        ch = value[self.cursor]
        matching = MATCHING_PAIRS.get(ch)
        if matching is None:
            return
        # Determine direction
        if ch in "([{<":
            pos = self._find_matching_pair_forward(self.cursor, value, ch, matching)
        else:
            pos = self._find_matching_pair_backward(self.cursor, value, matching, ch)
        if pos is not None:
            self._move_cursor_to(pos)

    # ── paste ──────────────────────────────────────────────────────────

    def _paste_after(self) -> None:
        """Paste from register after the cursor."""
        text = self._get_register_text()
        if not text:
            return
        self._input._push_undo()
        value = self._input.value
        cursor = self.cursor
        self._input.value = value[:cursor] + text + value[cursor:]
        self._move_cursor_to(cursor + len(text))
        self._last_change = _Change(is_insert_batch=True, insert_start_cursor=cursor, insert_text=text)

    def _paste_before(self) -> None:
        """Paste from register before the cursor."""
        text = self._get_register_text()
        if not text:
            return
        self._input._push_undo()
        value = self._input.value
        cursor = self.cursor
        self._input.value = value[:cursor] + text + value[cursor:]
        # Cursor stays at same position (before pasted text)
        self._last_change = _Change(is_insert_batch=True, insert_start_cursor=cursor, insert_text=text)

    # ── undo ───────────────────────────────────────────────────────────

    def _undo_normal(self, count: int) -> None:
        """Undo last change(s)."""
        for _ in range(count):
            if len(self._input._undo_stack) == 0:
                break
            self._input._pop_undo()

    # ── repeat last change ─────────────────────────────────────────────

    def _repeat_last_change(self) -> None:
        """Repeat the last editing change."""
        lc = self._last_change
        if lc is None:
            return

        if lc.is_insert_batch:
            # Replay insert: type the same text at current cursor
            text = lc.insert_text
            self._input._push_undo()
            value = self._input.value
            cursor = self.cursor
            self._input.value = value[:cursor] + text + value[cursor:]
            self._move_cursor_to(cursor + len(text))
            return

        if lc.operator is None or lc.motion_range is None:
            return

        op = lc.operator
        rng = lc.motion_range
        start = max(0, min(rng[0], len(self._input.value)))
        end = max(start, min(rng[1], len(self._input.value)))
        self._op_exec(op, start, end)

    # ── registers ──────────────────────────────────────────────────────

    def _effective_register(self) -> str:
        if self._op_register and self._op_register not in ('"', ):
            return self._op_register
        return '"'

    def _store_register(self, name: str, text: str) -> None:
        if name == '"':
            self._unnamed_register = text
        elif len(name) == 1 and name.isalpha():
            self._named_registers[name] = text

    def _get_register_text(self) -> str:
        reg = self._effective_register()
        if reg == '"':
            return self._unnamed_register
        return self._named_registers.get(reg, "")

    # ── cursor movement helpers ────────────────────────────────────────

    def _move_cursor_to(self, pos: int) -> None:
        self.cursor = max(0, min(pos, len(self._input.value)))

    def _move_left(self) -> None:
        if self.cursor <= 0:
            return
        gs = _graphemes(self._input.value[: self.cursor])
        if gs:
            self.cursor -= len(gs[-1])

    def _move_right(self) -> None:
        if self.cursor >= len(self._input.value):
            return
        gs = _graphemes(self._input.value[self.cursor :])
        if gs:
            self.cursor += len(gs[0])

    def _move_left_n(self, n: int) -> None:
        for _ in range(n):
            self._move_left()

    def _move_right_n(self, n: int) -> None:
        for _ in range(n):
            self._move_right()

    def _move_word_backward(self) -> None:
        cursor = self.cursor
        value = self._input.value
        if cursor <= 0:
            return
        # Skip whitespace backwards
        while cursor > 0 and is_whitespace_char(value[cursor - 1]):
            cursor -= 1
        if cursor <= 0:
            self.cursor = 0
            return
        # Determine category
        ch = value[cursor - 1]
        is_punct = is_punctuation_char(ch)
        while cursor > 0:
            prev = value[cursor - 1]
            if is_whitespace_char(prev):
                break
            if is_punctuation_char(prev) != is_punct:
                break
            cursor -= 1
        self.cursor = cursor

    def _move_word_forward(self) -> None:
        cursor = self.cursor
        value = self._input.value
        if cursor >= len(value):
            return
        # Step 1: if on word/punct, skip to end of current word
        ch = value[cursor]
        if not is_whitespace_char(ch):
            is_punct = is_punctuation_char(ch)
            while cursor < len(value):
                cur_ch = value[cursor]
                if is_whitespace_char(cur_ch):
                    break
                if is_punctuation_char(cur_ch) != is_punct:
                    break
                cursor += 1
        # Step 2: skip whitespace
        while cursor < len(value) and is_whitespace_char(value[cursor]):
            cursor += 1
        self.cursor = cursor

    def _move_word_backward_n(self, n: int) -> None:
        for _ in range(n):
            self._move_word_backward()

    def _move_word_forward_n(self, n: int) -> None:
        for _ in range(n):
            self._move_word_forward()

    def _move_word_end_forward(self) -> None:
        cursor = self.cursor
        value = self._input.value
        if cursor >= len(value):
            return
        # Skip to end of current word then skip whitespace then end of next word
        # First skip whitespace
        while cursor < len(value) and is_whitespace_char(value[cursor]):
            cursor += 1
        if cursor >= len(value):
            self.cursor = len(value)
            return
        # Skip to end of word
        ch = value[cursor]
        is_punct = is_punctuation_char(ch)
        while cursor < len(value):
            cur_ch = value[cursor]
            if is_whitespace_char(cur_ch):
                break
            if is_punctuation_char(cur_ch) != is_punct:
                break
            cursor += 1
        # e positions cursor on last char
        if cursor > self.cursor:
            self.cursor = cursor - 1
        elif cursor == self.cursor and cursor < len(value):
            self.cursor = cursor

    def _move_word_end_forward_n(self, n: int) -> None:
        for _ in range(n):
            self._move_word_end_forward()

    def _move_cursor_to_first_non_whitespace(self) -> None:
        value = self._input.value
        for i, ch in enumerate(value):
            if not is_whitespace_char(ch):
                self._move_cursor_to(i)
                return
        self._move_cursor_to(0)

    def _delete_chars_forward_n(self, n: int) -> None:
        for _ in range(n):
            if self.cursor >= len(self._input.value):
                break
            gs = _graphemes(self._input.value[self.cursor :])
            if not gs:
                break
            removed = gs[0]
            start = self.cursor
            end = start + len(removed)
            text = self._input.value[start:end]
            self._store_register(self._effective_register(), text)
            self._input._push_undo()
            self._input.value = self._input.value[:start] + self._input.value[end:]
            self._last_change = _Change(operator=Operator.DELETE, motion_range=(start, end))

    def _delete_chars_backward_n(self, n: int) -> None:
        for _ in range(n):
            if self.cursor <= 0:
                break
            gs = _graphemes(self._input.value[: self.cursor])
            if not gs:
                break
            removed = gs[-1]
            start = self.cursor - len(removed)
            text = self._input.value[start : self.cursor]
            self._store_register(self._effective_register(), text)
            self._input._push_undo()
            self._input.value = self._input.value[:start] + self._input.value[self.cursor :]
            self._move_cursor_to(start)
            self._last_change = _Change(operator=Operator.DELETE, motion_range=(start, start + len(removed)))

    def _delete_char_backward(self) -> None:
        self._delete_chars_backward_n(1)

    def _delete_char_forward(self) -> None:
        self._delete_chars_forward_n(1)

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _decode_char(data: str) -> str | None:
        """Decode a single printable character from raw input data."""
        ch = decode_kitty_printable(data)
        if ch is not None:
            return ch
        if len(data) == 1 and ord(data[0]) >= 0x20 and data != "\x7f":
            return data
        if len(data) >= 1 and ord(data[0]) >= 0x80 and not data.startswith("\x1b"):
            return data
        return None

    def _clear_sequence(self) -> None:
        """Reset all pending state."""
        self._op = None
        self._count_str = ""
        self._op_text_object_type = None
        self._op_register = None
        self._pending_g = False
        self._pending_motion_kind = None

