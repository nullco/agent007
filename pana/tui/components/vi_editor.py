# ruff: noqa: E701, E702
"""Vim modal editing for the multi-line Editor.

Wraps an Editor and intercepts keystrokes to implement vim modal editing:
Normal, Insert, Visual (char/line), Operator-Pending, and Replace modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

import grapheme

from pana.tui.escape_codes import EscapeCodes
from pana.tui.keybindings import get_editor_keybindings
from pana.tui.keys import decode_kitty_printable
from pana.tui.utils import is_punctuation_char, is_whitespace_char

if TYPE_CHECKING:
    pass

def _graphemes(text: str) -> list[str]:
    return list(grapheme.graphemes(text))

def _toggle_case(text: str) -> str:
    return "".join(ch.upper() if ch.islower() else ch.lower() if ch.isupper() else ch for ch in text)

MATCHING_PAIRS: dict[str, str] = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{"}

class ViMode(Enum):
    NORMAL = auto(); INSERT = auto(); VISUAL = auto(); VISUAL_LINE = auto()
    OPERATOR_PENDING = auto(); REPLACE_CHAR = auto()

class InsertVariant(Enum):
    PLAIN = auto(); APPEND = auto(); LINE_START = auto(); LINE_END = auto()
    BELOW = auto(); ABOVE = auto()

class Operator(Enum):
    DELETE = auto(); YANK = auto(); CHANGE = auto(); TOGGLE_CASE = auto()
    TO_UPPER = auto(); TO_LOWER = auto(); INDENT = auto(); OUTDENT = auto()

@dataclass
class _Change:
    operator: Operator | None = None
    start_line: int = 0; start_col: int = 0; end_line: int = 0; end_col: int = 0
    register_name: str | None = None
    is_insert_batch: bool = False
    insert_start_line: int = 0; insert_start_col: int = 0; insert_text: str = ""

class ViModeEditor:
    """Vim modal editing wrapper for the multi-line Editor."""

    def __init__(self, editor) -> None:
        self._ed = editor
        self._mode: ViMode = ViMode.NORMAL
        self._insert_variant: InsertVariant = InsertVariant.PLAIN
        self._visual_anchor_line: int = 0; self._visual_anchor_col: int = 0
        self._op: Operator | None = None
        self._count_str: str = ""
        self._op_text_object_type: str | None = None
        self._op_register: str | None = None
        self._pending_g: bool = False
        self._pending_motion_kind: str | None = None
        self._named_registers: dict[str, list[str]] = {}
        self._unnamed_register: list[str] | None = None
        self._last_change: _Change | None = None
        self._insert_start_line: int = 0; self._insert_start_col: int = 0
        self._last_search: str | None = None
        self._last_search_forward: bool = True
        self._marks: dict[str, tuple[int, int]] = {}
        self._last_find_char: str | None = None
        self._last_find_forward: bool = True
        self._last_find_kind: str = "f"

    def __getattr__(self, name: str):
        if name.startswith("_"): raise AttributeError(name)
        return getattr(self._ed, name)

    def invalidate(self) -> None: self._ed.invalidate()
    def render(self, width: int) -> list[str]:
        lines = self._ed.render(width)
        indicator = self._render_mode_indicator(width)
        lines.append(indicator)
        return lines

    def _render_mode_indicator(self, width: int) -> str:
        name = {
            ViMode.NORMAL: " NORMAL ",
            ViMode.INSERT: " INSERT ",
            ViMode.VISUAL: " VISUAL ",
            ViMode.VISUAL_LINE: " VISUAL LINE ",
            ViMode.OPERATOR_PENDING: " OP-PENDING ",
            ViMode.REPLACE_CHAR: " REPLACE ",
        }.get(self._mode, " ??? ")
        return f"{EscapeCodes.INVERSE_ON}{name}{EscapeCodes.INVERSE_OFF}"
    def get_text(self) -> str: return self._ed.get_text()
    def set_text(self, text: str) -> None: self._ed.set_text(text)
    def get_expanded_text(self) -> str: return self._ed.get_expanded_text()
    def add_to_history(self, text: str) -> None: self._ed.add_to_history(text)
    def set_autocomplete_provider(self, p) -> None: self._ed.set_autocomplete_provider(p)
    def set_padding_x(self, px: int) -> None: self._ed.set_padding_x(px)
    def is_showing_autocomplete(self) -> bool: return self._ed.is_showing_autocomplete()

    @property
    def focused(self) -> bool: return self._ed.focused
    @focused.setter
    def focused(self, f: bool) -> None: self._ed.focused = f
    @property
    def on_submit(self): return self._ed.on_submit
    @on_submit.setter
    def on_submit(self, cb): self._ed.on_submit = cb
    @property
    def on_change(self): return self._ed.on_change
    @on_change.setter
    def on_change(self, cb): self._ed.on_change = cb
    @property
    def on_action(self): return self._ed.on_action
    @on_action.setter
    def on_action(self, cb): self._ed.on_action = cb
    @property
    def disable_submit(self) -> bool: return self._ed.disable_submit
    @disable_submit.setter
    def disable_submit(self, v: bool) -> None: self._ed.disable_submit = v
    @property
    def mode(self) -> ViMode: return self._mode

    async def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()
        # Search-mode insert
        if self._pending_motion_kind == "search" and self._mode == ViMode.INSERT:
            if kb.matches(data, "tui.select.cancel"): self._cancel_search(); return
            if kb.matches(data, "tui.input.submit") or data == "\r": self._execute_search(); return
            await self._ed.handle_input(data); return
        # Escape
        if kb.matches(data, "tui.select.cancel"):
            if self._mode == ViMode.INSERT: self._exit_insert(); return
            if self._mode in (ViMode.OPERATOR_PENDING, ViMode.REPLACE_CHAR, ViMode.VISUAL, ViMode.VISUAL_LINE):
                self._clear_sequence(); self._mode = ViMode.NORMAL; return
        if self._mode == ViMode.INSERT: await self._ed.handle_input(data); return
        if self._mode == ViMode.OPERATOR_PENDING: await self._handle_operator_pending(data, kb); return
        if self._mode == ViMode.REPLACE_CHAR: await self._handle_replace_char(data, kb); return
        if self._mode in (ViMode.VISUAL, ViMode.VISUAL_LINE): await self._handle_visual(data, kb); return
        # NORMAL
        if self._ed.on_action:
            for a in kb.get_app_actions():
                if kb.matches(data, a): self._ed.on_action(a); return
        if kb.matches(data, "tui.editor.cursorUp"): self._ed._move_cursor(-1, 0); return
        if kb.matches(data, "tui.editor.cursorDown"): self._ed._move_cursor(1, 0); return
        if kb.matches(data, "tui.input.submit"):
            if not self._ed.disable_submit and self._ed.on_submit:
                await self._ed.on_submit(self._ed.get_text())
            return
        if kb.matches(data, "tui.input.tab"): await self._ed._handle_tab(); return
        ch = self._decode_char(data)
        if ch is not None: await self._dispatch_normal_char(ch)

    # ── normal dispatch / commands ─────────────────────────────────────

    async def _dispatch_normal_char(self, ch: str) -> None:
        if ch.isdigit() and ch != "0": self._count_str += ch; return
        count = int(self._count_str) if self._count_str else 1
        if self._pending_g: self._handle_g_sequence(ch, count); return
        if ch == '"' and self._op_register is None and not self._count_str:
            self._op_register = '"'; return
        if self._op_register == '"': self._op_register = ch; return
        if ch == "m" and not self._count_str:
            self._pending_motion_kind = "set_mark"
            self._mode = ViMode.OPERATOR_PENDING; return
        if ch in ("d", "y", "c") and not self._count_str:
            self._op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE}[ch]
            self._mode = ViMode.OPERATOR_PENDING; return
        await self._execute_normal_command(count, ch)

    async def _execute_normal_command(self, count: int, ch: str) -> None:
        cmd = ch; cl = self._ed._cursor_line; cc = self._ed._cursor_col
        lines = self._ed._lines
        if cmd == "h":   self._move_cursor_n(0, -1, count)
        elif cmd == "l": self._move_cursor_n(0, 1, count)
        elif cmd == "k": self._move_cursor_n(-1, 0, count)
        elif cmd == "j": self._move_cursor_n(1, 0, count)
        elif cmd == "w": self._move_word_forward_n(count)
        elif cmd == "b": self._move_word_backward_n(count)
        elif cmd == "e": self._move_word_end_forward_n(count)
        elif cmd == "0": self._ed._set_cursor_col(0)
        elif cmd == "$": self._ed._set_cursor_col(len(lines[cl]))
        elif cmd == "^": self._move_to_first_non_ws_on_line()
        elif cmd == "G": self._ed._cursor_line = len(lines) - 1; self._ed._set_cursor_col(len(lines[self._ed._cursor_line]))
        elif cmd == "f": self._start_pending_find("f")
        elif cmd == "F": self._start_pending_find("F")
        elif cmd == "t": self._start_pending_find("t")
        elif cmd == "T": self._start_pending_find("T")
        elif cmd == ";": self._repeat_find(True, count)
        elif cmd == ",": self._repeat_find(False, count)
        elif cmd == "%": self._jump_match_pair()
        elif cmd == "x":
            for _ in range(count):
                if cc < len(lines[cl]): self._op_exec(Operator.DELETE, cc, cc + 1, cl, cl)
        elif cmd == "X":
            for _ in range(count):
                if cc > 0: self._op_exec(Operator.DELETE, cc - 1, cc, cl, cl)
        elif cmd == "D": self._op_exec(Operator.DELETE, cc, len(lines[cl]), cl, cl)
        elif cmd == "C": self._op_exec(Operator.CHANGE, cc, len(lines[cl]), cl, cl)
        elif cmd == "s": self._op_exec(Operator.CHANGE, cc, min(cc + count, len(lines[cl])), cl, cl)
        elif cmd == "S": self._op_exec(Operator.CHANGE, 0, len(lines[cl]), cl, cl)
        elif cmd == "~": self._op_exec(Operator.TOGGLE_CASE, cc, min(cc + count, len(lines[cl])), cl, cl)
        elif cmd == "p":
            for _ in range(count): self._paste_after()
        elif cmd == "P":
            for _ in range(count): self._paste_before()
        elif cmd == "r": self._mode = ViMode.REPLACE_CHAR
        elif cmd in ("d", "y", "c"):
            self._op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE}[cmd]
            self._mode = ViMode.OPERATOR_PENDING
        elif cmd == "g": self._pending_g = True
        elif cmd == "v": self._mode = ViMode.VISUAL; self._visual_anchor_line = cl; self._visual_anchor_col = cc
        elif cmd == "V": self._mode = ViMode.VISUAL_LINE; self._visual_anchor_line = cl; self._visual_anchor_col = 0
        elif cmd == "i": self._enter_insert(InsertVariant.PLAIN)
        elif cmd == "a": self._enter_insert(InsertVariant.APPEND)
        elif cmd == "I": self._enter_insert(InsertVariant.LINE_START)
        elif cmd == "A": self._enter_insert(InsertVariant.LINE_END)
        elif cmd == "o": self._enter_insert(InsertVariant.BELOW)
        elif cmd == "O": self._enter_insert(InsertVariant.ABOVE)
        elif cmd == "u":
            for _ in range(count): self._ed._undo()
        elif cmd == ".":
            for _ in range(count): self._repeat_last_change()
        elif cmd == "/": self._start_pending_search(True)
        elif cmd == "?": self._start_pending_search(False)
        elif cmd == "n": self._repeat_search(True, count)
        elif cmd == "N": self._repeat_search(False, count)
        elif cmd == "'": self._pending_motion_kind = "mj_line"; self._mode = ViMode.OPERATOR_PENDING; return
        elif cmd == "`": self._pending_motion_kind = "mark_jump"; self._mode = ViMode.OPERATOR_PENDING; return
        elif cmd == ">": self._shift_line_right()
        elif cmd == "<": self._shift_line_left()
        self._clear_sequence()

    def _handle_g_sequence(self, ch: str, count: int) -> None:
        self._pending_g = False; cl = self._ed._cursor_line; lines = self._ed._lines
        if ch == "g": self._ed._cursor_line = 0; self._ed._set_cursor_col(0)
        elif ch == "~": self._op_exec(Operator.TOGGLE_CASE, self._ed._cursor_col, min(self._ed._cursor_col + count, len(lines[cl])), cl, cl)
        elif ch == "u": self._op_exec(Operator.TO_LOWER, self._ed._cursor_col, len(lines[cl]), cl, cl)
        elif ch == "U": self._op_exec(Operator.TO_UPPER, self._ed._cursor_col, len(lines[cl]), cl, cl)
        self._clear_sequence()

    # ── operator-pending ───────────────────────────────────────────────

    async def _handle_operator_pending(self, data: str, kb) -> None:
        ch = self._decode_char(data)
        if ch is not None:
            if ch.isdigit() and ch != "0": self._count_str += ch; return
            if self._op is None: self._handle_pure_motion(ch)
            else: self._finish_operator(ch)

    def _handle_pure_motion(self, ch: str) -> None:
        kind = self._pending_motion_kind; count = int(self._count_str) if self._count_str else 1
        if kind == "set_mark": self._set_mark(ch); self._mode = ViMode.NORMAL; self._clear_sequence(); return
        if kind == "mark_jump": self._jump_to_mark(ch); self._mode = ViMode.NORMAL; self._clear_sequence(); return
        if kind == "mj_line": self._jump_to_mark_line(ch); self._mode = ViMode.NORMAL; self._clear_sequence(); return
        if kind in ("f", "F", "t", "T"):
            for _ in range(count):
                fn = self._find_char_on_line if kind in ("f", "F") else self._till_char_on_line
                pos = fn(kind in ("f", "t"))
                if pos is not None: self._ed._set_cursor_col(pos)
                else: break
            self._last_find_kind = kind; self._mode = ViMode.NORMAL; self._clear_sequence(); return
        self._mode = ViMode.NORMAL; self._clear_sequence()

    def _finish_operator(self, ch: str) -> None:
        if self._op is None: self._mode = ViMode.NORMAL; self._clear_sequence(); return
        op = self._op; count = int(self._count_str) if self._count_str else 1; cl = self._ed._cursor_line
        op_char = {Operator.DELETE: "d", Operator.YANK: "y", Operator.CHANGE: "c"}.get(op)
        if ch == op_char:
            self._op_exec_linewise(op, cl, min(cl + count, len(self._ed._lines)))
            self._mode = ViMode.NORMAL; self._clear_sequence(); return
        if ch in ("i", "a"): self._op_text_object_type = ch; return
        if self._op_text_object_type:
            self._op_exec_text_object(self._op_text_object_type + ch)
            self._mode = ViMode.NORMAL; self._clear_sequence(); return
        if ch in ("f", "F", "t", "T"): self._pending_motion_kind = ch; return
        if self._pending_motion_kind in ("f", "F", "t", "T"):
            kind = self._pending_motion_kind
            fn = self._find_char_on_line if kind in ("f", "F") else self._till_char_on_line
            pos = fn(kind in ("f", "t"))
            if pos is not None:
                sc, ec = self._ed._cursor_col, pos
                if kind in ("f", "F"): ec += 1
                self._op_exec(op, min(sc, ec), max(sc, ec), cl, cl)
            self._mode = ViMode.NORMAL; self._clear_sequence(); return
        motion = self._compute_motion(ch, count)
        if motion is not None:
            sl, sc = cl, self._ed._cursor_col; el, ec = motion
            inclusive = ch in ("e", "$", "l")
            if inclusive and ec < len(self._ed._lines[el]): ec += 1
            self._op_exec(op, sc, ec, sl, el)
            self._mode = ViMode.NORMAL; self._clear_sequence(); return
        self._mode = ViMode.NORMAL; self._clear_sequence()

    def _compute_motion(self, ch: str, count: int) -> tuple[int, int] | None:
        sl, sc = self._ed._cursor_line, self._ed._cursor_col
        try:
            if ch == "h":   self._move_cursor_n(0, -1, count)
            elif ch == "l": self._move_cursor_n(0, 1, count)
            elif ch == "j": self._move_cursor_n(1, 0, count)
            elif ch == "k": self._move_cursor_n(-1, 0, count)
            elif ch == "w": self._move_word_forward_n(count)
            elif ch == "b": self._move_word_backward_n(count)
            elif ch == "e": self._move_word_end_forward_n(count)
            elif ch == "0": self._ed._set_cursor_col(0)
            elif ch == "$": self._ed._set_cursor_col(len(self._ed._lines[self._ed._cursor_line]))
            elif ch == "^": self._move_to_first_non_ws_on_line()
            elif ch == "G": self._ed._cursor_line = len(self._ed._lines) - 1; self._ed._set_cursor_col(len(self._ed._lines[self._ed._cursor_line]))
            else: return None
            return (self._ed._cursor_line, self._ed._cursor_col)
        finally: self._ed._cursor_line, self._ed._cursor_col = sl, sc

    # ── operators ──────────────────────────────────────────────────

    def _op_exec(self, op: Operator, sc: int, ec: int, sl: int, el: int) -> None:
        lines = self._ed._lines
        text = lines[sl][sc:ec] if sl == el else "\n".join(
            (lines[i] if i > sl else lines[i][sc:]) for i in range(sl, el + 1))
        reg = self._effective_register()
        if op == Operator.DELETE:
            self._store_register(reg, text); self._ed._push_undo()
            self._delete_range(sl, sc, el, ec)
            self._last_change = _Change(operator=op, start_line=sl, start_col=sc, end_line=el, end_col=ec, register_name=reg)
        elif op == Operator.YANK:
            self._store_register(reg, text)
        elif op == Operator.CHANGE:
            self._store_register(reg, text); self._ed._push_undo()
            self._delete_range(sl, sc, el, ec)
            self._last_change = _Change(operator=op, start_line=sl, start_col=sc, end_line=el, end_col=ec, register_name=reg)
            self._enter_insert(InsertVariant.PLAIN)
        elif op in (Operator.TOGGLE_CASE, Operator.TO_LOWER, Operator.TO_UPPER):
            self._ed._push_undo()
            fn = {Operator.TOGGLE_CASE: _toggle_case, Operator.TO_LOWER: str.lower, Operator.TO_UPPER: str.upper}[op]
            self._apply_case(fn, sl, sc, el, ec)
            self._last_change = _Change(operator=op, start_line=sl, start_col=sc, end_line=el, end_col=ec)

    def _op_exec_linewise(self, op: Operator, sl: int, el: int) -> None:
        lines = self._ed._lines; text = "\n".join(lines[sl:el])
        if op in (Operator.DELETE, Operator.CHANGE):
            self._store_register(self._effective_register(), text); self._ed._push_undo()
            del self._ed._lines[sl:el]
            if not self._ed._lines: self._ed._lines = [""]
            self._ed._cursor_line = max(0, sl - 1); self._ed._set_cursor_col(0)
            self._last_change = _Change(operator=op, start_line=sl, start_col=0, end_line=el, end_col=0)
            if op == Operator.CHANGE: self._enter_insert(InsertVariant.PLAIN)
        elif op == Operator.YANK:
            self._store_register(self._effective_register(), text)

    def _delete_range(self, sl: int, sc: int, el: int, ec: int) -> None:
        lines = self._ed._lines
        if sl == el: line = lines[sl]; lines[sl] = line[:sc] + line[ec:]
        else: lines[sl] = lines[sl][:sc] + lines[el][ec:]; del lines[sl + 1:el + 1]
        self._ed._cursor_line = sl; self._ed._set_cursor_col(sc)
        if self._ed.on_change: self._ed.on_change(self._ed.get_text())

    def _apply_case(self, fn, sl: int, sc: int, el: int, ec: int) -> None:
        lines = self._ed._lines
        if sl == el: ln = lines[sl]; lines[sl] = ln[:sc] + fn(ln[sc:ec]) + ln[ec:]
        else:
            for i in range(sl, el + 1):
                ln = lines[i]
                if i == sl: lines[i] = ln[:sc] + fn(ln[sc:])
                elif i == el: lines[i] = fn(ln[:ec]) + ln[ec:]
                else: lines[i] = fn(ln)
        if self._ed.on_change: self._ed.on_change(self._ed.get_text())

    # ── text objects ───────────────────────────────────────────────

    def _op_exec_text_object(self, obj: str) -> None:
        if self._op is None: return
        rng = self._text_object_range(obj)
        if rng: self._op_exec(self._op, rng[1], rng[3], rng[0], rng[2])

    def _text_object_range(self, obj: str) -> tuple[int, int, int, int] | None:
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; value = self._ed._lines[cl]
        if obj in ("iw", "aw"):
            r = self._word_text_object(cl, cc, obj == "aw")
            return (cl, r[0], cl, r[1]) if r else None
        if obj in ("iW", "aW"):
            r = self._WORD_text_object(cl, cc, obj == "aW")
            return (cl, r[0], cl, r[1]) if r else None
        if len(obj) == 2 and obj[0] in ("i", "a"):
            delim = obj[1]
            if delim in ('"', "'", "`"):
                r = self._quote_text_object(cl, cc, delim, obj[0] == "a")
                return (cl, r[0], cl, r[1]) if r else None
            m = MATCHING_PAIRS.get(delim)
            if m is not None:
                r = self._paired_text_object(cl, cc, value, delim, m, obj[0] == "a")
                return (cl, r[0], cl, r[1]) if r else None
        return None

    def _word_text_object(self, line: int, col: int, incl_ws: bool) -> tuple[int, int] | None:
        v = self._ed._lines[line]
        if not v: return None
        s, e = col, col; ch_at = v[col] if col < len(v) else " "
        if is_whitespace_char(ch_at):
            while s > 0 and is_whitespace_char(v[s - 1]): s -= 1
            while e < len(v) and is_whitespace_char(v[e]): e += 1
            if incl_ws and s > 0 and not is_whitespace_char(v[s - 1]):
                while s > 0 and not is_whitespace_char(v[s - 1]): s -= 1
            return (s, e)
        is_p = is_punctuation_char(ch_at)
        while s > 0:
            pc = v[s - 1]
            if is_whitespace_char(pc) or is_punctuation_char(pc) != is_p: break
            s -= 1
        while e < len(v):
            nc = v[e]
            if is_whitespace_char(nc) or is_punctuation_char(nc) != is_p: break
            e += 1
        if incl_ws:
            while e < len(v) and is_whitespace_char(v[e]): e += 1
        return (s, e)

    def _WORD_text_object(self, line: int, col: int, incl_ws: bool) -> tuple[int, int] | None:
        v = self._ed._lines[line]
        if not v: return None
        s, e = col, col; ch_at = v[col] if col < len(v) else " "
        if is_whitespace_char(ch_at):
            while s > 0 and is_whitespace_char(v[s - 1]): s -= 1
            while e < len(v) and is_whitespace_char(v[e]): e += 1
            if incl_ws and s > 0 and not is_whitespace_char(v[s - 1]):
                while s > 0 and not is_whitespace_char(v[s - 1]): s -= 1
            return (s, e)
        while s > 0 and not is_whitespace_char(v[s - 1]): s -= 1
        while e < len(v) and not is_whitespace_char(v[e]): e += 1
        if incl_ws:
            while e < len(v) and is_whitespace_char(v[e]): e += 1
        return (s, e)

    def _paired_text_object(self, line: int, col: int, value: str, od: str, cd: str, incl: bool) -> tuple[int, int] | None:
        ch_at = value[col] if col < len(value) else ""
        if ch_at == od:
            e = self._find_matching_pair_fwd(col, value, od, cd)
            if e is None: return None
            s = col
        elif ch_at == cd:
            s = self._find_matching_pair_bwd(col, value, od, cd)
            if s is None: return None
            e = col
        else:
            e = self._find_next_close(value, col, od, cd)
            if e is None: return None
            s = self._find_matching_pair_bwd(e, value, od, cd)
            if s is None: return None
        return (s, e + 1) if incl else (s + 1, e)

    def _quote_text_object(self, line: int, col: int, q: str, incl: bool) -> tuple[int, int] | None:
        v = self._ed._lines[line]
        end = v.find(q, col + 1 if col < len(v) and v[col] == q else col)
        if end == -1: return None
        lim = col if (col < len(v) and v[col] == q) else col + 1
        start = v.rfind(q, 0, lim)
        if start == -1: return None
        return (start, end + 1) if incl else (start + 1, end)

    def _find_matching_pair_fwd(self, pos: int, v: str, od: str, cd: str) -> int | None:
        depth = 0
        for i in range(pos, len(v)):
            if v[i] == od and not self._escaped(v, i): depth += 1
            elif v[i] == cd and not self._escaped(v, i):
                depth -= 1
                if depth == 0: return i
        return None

    def _find_matching_pair_bwd(self, pos: int, v: str, od: str, cd: str) -> int | None:
        depth = 0
        for i in range(pos, -1, -1):
            if v[i] == cd and not self._escaped(v, i): depth += 1
            elif v[i] == od and not self._escaped(v, i):
                depth -= 1
                if depth == 0: return i
        return None

    def _find_next_close(self, v: str, cursor: int, od: str, cd: str) -> int | None:
        depth = 0
        for i in range(cursor, len(v)):
            if v[i] == od and not self._escaped(v, i): depth += 1
            elif v[i] == cd and not self._escaped(v, i):
                if depth == 0: return i
                depth -= 1
        return None

    @staticmethod
    def _escaped(v: str, pos: int) -> bool:
        cnt = 0; i = pos - 1
        while i >= 0 and v[i] == "\\": cnt += 1; i -= 1
        return cnt % 2 == 1

    # ── insert mode ────────────────────────────────────────────────

    def _enter_insert(self, variant: InsertVariant) -> None:
        self._mode = ViMode.INSERT; self._insert_variant = variant
        self._insert_start_line = self._ed._cursor_line
        self._insert_start_col = self._ed._cursor_col
        lines = self._ed._lines; cl = self._ed._cursor_line
        if variant == InsertVariant.APPEND:
            if self._ed._cursor_col < len(lines[cl]):
                self._ed._set_cursor_col(self._ed._cursor_col + 1)
        elif variant == InsertVariant.LINE_START:
            self._move_to_first_non_ws_on_line()
        elif variant == InsertVariant.LINE_END:
            self._ed._set_cursor_col(len(lines[cl]))
        elif variant == InsertVariant.BELOW:
            self._ed._lines.insert(cl + 1, "")
            self._ed._cursor_line = cl + 1; self._ed._set_cursor_col(0)
        elif variant == InsertVariant.ABOVE:
            self._ed._lines.insert(cl, "")
            self._ed._cursor_line = cl; self._ed._set_cursor_col(0)
        self._ed._push_undo(); self._ed._last_action = None

    def _exit_insert(self) -> None:
        self._mode = ViMode.NORMAL
        if self._insert_variant in (InsertVariant.PLAIN, InsertVariant.LINE_START):
            if self._ed._cursor_col > 0:
                self._ed._set_cursor_col(self._ed._cursor_col - 1)
        text = self._ed.get_text()
        self._last_change = _Change(is_insert_batch=True,
            insert_start_line=self._insert_start_line, insert_start_col=self._insert_start_col, insert_text=text)

    # ── visual mode ────────────────────────────────────────────────

    async def _handle_visual(self, data: str, kb) -> None:
        if kb.matches(data, "tui.editor.cursorUp"): self._ed._move_cursor(-1, 0); self._ed._last_action = None; return
        if kb.matches(data, "tui.editor.cursorDown"): self._ed._move_cursor(1, 0); self._ed._last_action = None; return
        if kb.matches(data, "tui.editor.cursorLeft"): self._ed._move_cursor(0, -1); self._ed._last_action = None; return
        if kb.matches(data, "tui.editor.cursorRight"): self._ed._move_cursor(0, 1); self._ed._last_action = None; return
        ch = self._decode_char(data)
        if ch is not None:
            if ch in ("d", "y", "c", "~"):
                op = {"d": Operator.DELETE, "y": Operator.YANK, "c": Operator.CHANGE, "~": Operator.TOGGLE_CASE}[ch]
                sl, sc, el, ec = self._visual_range()
                self._op_exec(op, sc, ec, sl, el)
                self._mode = ViMode.NORMAL; self._clear_sequence(); return
            if ch == "v": self._mode = ViMode.NORMAL; self._clear_sequence(); return
            await self._dispatch_normal_char(ch)

    def _visual_range(self) -> tuple[int, int, int, int]:
        al = self._visual_anchor_line; ac = self._visual_anchor_col
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; lines = self._ed._lines
        if self._mode == ViMode.VISUAL_LINE:
            return (min(al, cl), 0, max(al, cl) + 1, 0)
        if al < cl or (al == cl and ac <= cc):
            sl, sc, el, ec = al, ac, cl, cc
        else:
            sl, sc, el, ec = cl, cc, al, ac
        if ec < len(lines[el]): ec += 1
        return (sl, sc, el, ec)

    # ── replace-char ───────────────────────────────────────────────

    async def _handle_replace_char(self, data: str, kb) -> None:
        ch = self._decode_char(data)
        if ch is not None:
            cl = self._ed._cursor_line; cc = self._ed._cursor_col; lines = self._ed._lines
            if cc < len(lines[cl]):
                self._ed._push_undo()
                ln = lines[cl]
                self._ed._lines[cl] = ln[:cc] + ch + ln[cc + 1:]
                self._last_change = _Change(operator=Operator.CHANGE, start_line=cl, start_col=cc, end_line=cl, end_col=cc + 1)
        self._mode = ViMode.NORMAL; self._clear_sequence()

    # ── find / till ────────────────────────────────────────────────

    def _start_pending_find(self, kind: str) -> None:
        self._pending_motion_kind = kind
        self._last_find_forward = kind in ("f", "t")
        self._mode = ViMode.OPERATOR_PENDING; self._op = None

    def _find_char_on_line(self, forward: bool) -> int | None:
        if self._last_find_char is None: return None
        line = self._ed._lines[self._ed._cursor_line]; cc = self._ed._cursor_col
        if forward:
            idx = line.find(self._last_find_char, cc + 1)
        else:
            idx = line.rfind(self._last_find_char, 0, cc)
        return idx if idx != -1 else None

    def _till_char_on_line(self, forward: bool) -> int | None:
        pos = self._find_char_on_line(forward)
        if pos is None: return None
        return max(pos - 1, 0) if forward else min(pos + 1, len(self._ed._lines[self._ed._cursor_line]))

    def _repeat_find(self, same_direction: bool, count: int) -> None:
        if self._last_find_char is None: return
        forward = self._last_find_forward if same_direction else not self._last_find_forward
        kind = self._last_find_kind
        for _ in range(count):
            fn = self._find_char_on_line if kind in ("f", "F") else self._till_char_on_line
            pos = fn(forward)
            if pos is not None: self._ed._set_cursor_col(pos)
            else: break

    # ── search ─────────────────────────────────────────────────────

    def _start_pending_search(self, forward: bool) -> None:
        self._last_search_forward = forward; self._pending_motion_kind = "search"
        self._mode = ViMode.INSERT; self._insert_variant = InsertVariant.PLAIN
        # Clear the editor temporarily for search input
        self._search_old_lines = list(self._ed._lines)
        self._search_old_cl = self._ed._cursor_line
        self._search_old_cc = self._ed._cursor_col
        self._ed._lines = [""]; self._ed._cursor_line = 0; self._ed._set_cursor_col(0)

    def _cancel_search(self) -> None:
        if self._search_old_lines is not None:
            self._ed._lines = self._search_old_lines
            self._ed._cursor_line = self._search_old_cl
            self._ed._set_cursor_col(self._search_old_cc)
            self._search_old_lines = None
        self._pending_motion_kind = None; self._mode = ViMode.NORMAL

    def _execute_search(self) -> None:
        pattern = self._ed._lines[0] if self._ed._lines else ""
        # Restore old content
        if self._search_old_lines is not None:
            self._ed._lines = self._search_old_lines
            self._ed._cursor_line = self._search_old_cl
            self._ed._set_cursor_col(self._search_old_cc)
            self._search_old_lines = None
        if pattern: self._last_search = pattern
        else: pattern = self._last_search
        if pattern:
            self._search(pattern, self._last_search_forward)
        self._pending_motion_kind = None; self._mode = ViMode.NORMAL

    def _repeat_search(self, same_dir: bool, count: int) -> None:
        if self._last_search is None: return
        forward = self._last_search_forward if same_dir else not self._last_search_forward
        for _ in range(count): self._search(self._last_search, forward)

    def _search(self, pattern: str, forward: bool) -> None:
        lines = self._ed._lines; cl = self._ed._cursor_line; cc = self._ed._cursor_col
        if forward:
            for l in range(cl, len(lines)):
                start = cc + 1 if l == cl else 0
                idx = lines[l].find(pattern, start)
                if idx != -1: self._ed._cursor_line = l; self._ed._set_cursor_col(idx); return
            for l in range(0, cl):
                idx = lines[l].find(pattern)
                if idx != -1: self._ed._cursor_line = l; self._ed._set_cursor_col(idx); return
        else:
            for l in range(cl, -1, -1):
                end = cc if l == cl else len(lines[l])
                idx = lines[l].rfind(pattern, 0, end)
                if idx != -1: self._ed._cursor_line = l; self._ed._set_cursor_col(idx); return
            for l in range(len(lines) - 1, cl, -1):
                idx = lines[l].rfind(pattern)
                if idx != -1: self._ed._cursor_line = l; self._ed._set_cursor_col(idx); return

    # ── marks ──────────────────────────────────────────────────────

    def _set_mark(self, name: str) -> None:
        if len(name) == 1 and name.isalpha():
            self._marks[name] = (self._ed._cursor_line, self._ed._cursor_col)

    def _jump_to_mark(self, name: str) -> None:
        if name in self._marks:
            l, c = self._marks[name]
            self._ed._cursor_line = min(l, len(self._ed._lines) - 1)
            self._ed._set_cursor_col(min(c, len(self._ed._lines[self._ed._cursor_line])))

    def _jump_to_mark_line(self, name: str) -> None:
        if name in self._marks:
            l, _ = self._marks[name]
            self._ed._cursor_line = min(l, len(self._ed._lines) - 1)
            self._move_to_first_non_ws_on_line()

    # ── paste ──────────────────────────────────────────────────────

    def _paste_after(self) -> None:
        text = self._get_register_text()
        if not text: return
        self._ed._push_undo(); lines = self._ed._lines
        cl = self._ed._cursor_line; cc = self._ed._cursor_col
        paste_lines = text.split("\n")
        if len(paste_lines) == 1:
            ln = lines[cl]; lines[cl] = ln[:cc] + paste_lines[0] + ln[cc:]
            if self._ed.on_change: self._ed.on_change(self._ed.get_text())
        else:
            tail = lines[cl][cc:]
            lines[cl] = lines[cl][:cc] + paste_lines[0]
            for i, pl in enumerate(paste_lines[1:-1]):
                lines.insert(cl + 1 + i, pl)
            last_idx = cl + len(paste_lines) - 1
            lines.insert(last_idx, paste_lines[-1] + tail)
            self._ed._cursor_line = last_idx
            self._ed._set_cursor_col(len(paste_lines[-1]))
            if self._ed.on_change: self._ed.on_change(self._ed.get_text())
        self._last_change = _Change(is_insert_batch=True)

    def _paste_before(self) -> None:
        text = self._get_register_text()
        if not text: return
        self._ed._push_undo(); lines = self._ed._lines
        cl = self._ed._cursor_line; cc = self._ed._cursor_col
        paste_lines = text.split("\n")
        if len(paste_lines) == 1:
            ln = lines[cl]; lines[cl] = ln[:cc] + paste_lines[0] + ln[cc:]
            if self._ed.on_change: self._ed.on_change(self._ed.get_text())
        else:
            tail = lines[cl][cc:]
            lines[cl] = lines[cl][:cc] + paste_lines[0]
            for i, pl in enumerate(paste_lines[1:-1]):
                lines.insert(cl + 1 + i, pl)
            last_idx = cl + len(paste_lines) - 1
            lines.insert(last_idx, paste_lines[-1] + tail)
            if self._ed.on_change: self._ed.on_change(self._ed.get_text())
        self._last_change = _Change(is_insert_batch=True)

    # ── repeat ─────────────────────────────────────────────────────

    def _repeat_last_change(self) -> None:
        lc = self._last_change
        if lc is None: return
        if lc.is_insert_batch: return  # too complex for dot repeat in multiline
        if lc.operator is None: return
        self._op_exec(lc.operator, lc.start_col, lc.end_col, lc.start_line, lc.end_line)

    # ── registers ──────────────────────────────────────────────────

    def _effective_register(self) -> str:
        if self._op_register and self._op_register != '"': return self._op_register
        return '"'

    def _store_register(self, name: str, text: str) -> None:
        if name == '"': self._unnamed_register = [text]
        elif len(name) == 1 and name.isalpha():
            self._named_registers[name] = [text]

    def _get_register_text(self) -> str:
        reg = self._effective_register()
        store = self._named_registers.get(reg) if reg != '"' else self._unnamed_register
        return store[0] if store else ""

    # ── cursor movement ────────────────────────────────────────────

    def _move_cursor_n(self, dl: int, dc: int, n: int) -> None:
        for _ in range(n): self._ed._move_cursor(dl, dc)

    def _move_word_forward(self) -> None:
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; lines = self._ed._lines
        if cl >= len(lines): return
        ln = lines[cl]
        if cc >= len(ln):
            if cl + 1 < len(lines): self._ed._cursor_line = cl + 1; self._ed._set_cursor_col(0)
            return
        ch = ln[cc]
        if not is_whitespace_char(ch):
            is_p = is_punctuation_char(ch)
            while cc < len(ln):
                cch = ln[cc]
                if is_whitespace_char(cch) or is_punctuation_char(cch) != is_p: break
                cc += 1
        while cc < len(ln) and is_whitespace_char(ln[cc]): cc += 1
        if cc >= len(ln) and cl + 1 < len(lines):
            self._ed._cursor_line = cl + 1; self._ed._set_cursor_col(0)
        else:
            self._ed._set_cursor_col(cc)

    def _move_word_backward(self) -> None:
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; lines = self._ed._lines
        if cc == 0:
            if cl > 0:
                self._ed._cursor_line = cl - 1
                self._ed._set_cursor_col(len(lines[cl - 1]))
            return
        ln = lines[cl]; cc -= 1
        while cc >= 0 and is_whitespace_char(ln[cc]): cc -= 1
        if cc < 0: self._ed._set_cursor_col(0); return
        ch = ln[cc]; is_p = is_punctuation_char(ch)
        while cc >= 0:
            pc = ln[cc]
            if is_whitespace_char(pc) or is_punctuation_char(pc) != is_p: break
            cc -= 1
        self._ed._set_cursor_col(cc + 1)

    def _move_word_forward_n(self, n: int) -> None:
        for _ in range(n): self._move_word_forward()

    def _move_word_backward_n(self, n: int) -> None:
        for _ in range(n): self._move_word_backward()

    def _move_word_end_forward(self) -> None:
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; lines = self._ed._lines
        ln = lines[cl]
        while cc < len(ln) and is_whitespace_char(ln[cc]): cc += 1
        if cc >= len(ln): return
        ch = ln[cc]; is_p = is_punctuation_char(ch)
        while cc < len(ln):
            cch = ln[cc]
            if is_whitespace_char(cch) or is_punctuation_char(cch) != is_p: break
            cc += 1
        self._ed._set_cursor_col(max(0, cc - 1))

    def _move_word_end_forward_n(self, n: int) -> None:
        for _ in range(n): self._move_word_end_forward()

    def _move_to_first_non_ws_on_line(self) -> None:
        cl = self._ed._cursor_line; ln = self._ed._lines[cl]
        for i, ch in enumerate(ln):
            if not is_whitespace_char(ch): self._ed._set_cursor_col(i); return
        self._ed._set_cursor_col(0)

    def _jump_match_pair(self) -> None:
        cl = self._ed._cursor_line; cc = self._ed._cursor_col; ln = self._ed._lines[cl]
        if cc >= len(ln): return
        ch = ln[cc]; matching = MATCHING_PAIRS.get(ch)
        if matching is None: return
        if ch in "([{":
            pos = self._find_matching_pair_fwd(cc, ln, ch, matching)
        else:
            pos = self._find_matching_pair_bwd(cc, ln, matching, ch)
        if pos is not None: self._ed._set_cursor_col(pos)

    def _shift_line_right(self) -> None:
        cl = self._ed._cursor_line
        self._ed._push_undo()
        self._ed._lines[cl] = "  " + self._ed._lines[cl]
        if self._ed.on_change: self._ed.on_change(self._ed.get_text())

    def _shift_line_left(self) -> None:
        cl = self._ed._cursor_line; ln = self._ed._lines[cl]
        if ln.startswith("  "):
            self._ed._push_undo(); self._ed._lines[cl] = ln[2:]
        elif ln.startswith(" "):
            self._ed._push_undo(); self._ed._lines[cl] = ln[1:]
        if self._ed.on_change: self._ed.on_change(self._ed.get_text())

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _decode_char(data: str) -> str | None:
        ch = decode_kitty_printable(data)
        if ch is not None: return ch
        if len(data) == 1 and ord(data[0]) >= 0x20 and data != "\x7f": return data
        if len(data) >= 1 and ord(data[0]) >= 0x80 and not data.startswith("\x1b"): return data
        return None

    def _clear_sequence(self) -> None:
        self._op = None; self._count_str = ""
        self._op_text_object_type = None; self._op_register = None
        self._pending_g = False; self._pending_motion_kind = None
