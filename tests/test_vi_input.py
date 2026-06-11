"""Smoke tests for ViModeInput component."""
from __future__ import annotations

from pana.tui.components.vi_input import ViMode, ViModeInput


def _mk(*, vi_mode_only: bool = True) -> ViModeInput:
    return ViModeInput(initial_value="hello world", vi_mode_only=vi_mode_only)


# ── Mode ───────────────────────────────────────────────────────────────


async def test_starts_in_normal_mode() -> None:
    vi = _mk()
    assert vi.mode == ViMode.NORMAL


async def test_enters_insert_mode_with_i() -> None:
    vi = _mk()
    await vi._dispatch_normal_char("i")
    assert vi.mode == ViMode.INSERT


async def test_esc_from_insert_returns_to_normal() -> None:
    vi = _mk()
    vi._mode = ViMode.INSERT
    vi._insert_variant = ViMode.INSERT  # will be fixed below
    from pana.tui.components.vi_input import InsertVariant
    vi._insert_variant = InsertVariant.PLAIN
    from pana.tui.keybindings import get_editor_keybindings
    kb = get_editor_keybindings()
    # Simulate Escape
    esc_data = "\x1b"
    await vi._handle_insert(esc_data, kb)
    assert vi.mode == ViMode.NORMAL


# ── Cursor movement in normal mode ─────────────────────────────────────


async def test_h_moves_left() -> None:
    vi = _mk()
    vi.cursor = 5  # on space in "hello world"
    await vi._dispatch_normal_char("h")
    assert vi.cursor == 4  # on 'o'


async def test_l_moves_right() -> None:
    vi = _mk()
    vi.cursor = 0
    await vi._dispatch_normal_char("l")
    assert vi.cursor == 1


async def test_w_moves_word_forward() -> None:
    vi = _mk()
    vi.cursor = 0
    await vi._dispatch_normal_char("w")
    # w from start of word moves to start of next word
    assert vi.cursor == 6  # start of "world"


async def test_b_moves_word_backward() -> None:
    vi = _mk()
    vi.cursor = 6
    await vi._dispatch_normal_char("b")
    assert vi.cursor == 0


async def test_0_moves_to_start() -> None:
    vi = _mk()
    vi.cursor = 5
    await vi._dispatch_normal_char("0")
    assert vi.cursor == 0


async def test_dollar_moves_to_end() -> None:
    vi = _mk()
    vi.cursor = 0
    await vi._dispatch_normal_char("$")
    assert vi.cursor == len("hello world")


async def test_caret_moves_to_first_non_ws() -> None:
    vi = ViModeInput(initial_value="   abc def", vi_mode_only=True)
    vi.cursor = 6
    await vi._dispatch_normal_char("^")
    assert vi.cursor == 3


# ── Editing ────────────────────────────────────────────────────────────


async def test_x_deletes_forward() -> None:
    vi = _mk()
    vi.cursor = 0  # on 'h'
    await vi._dispatch_normal_char("x")
    assert vi.value == "ello world"
    assert vi.cursor == 0


async def test_X_deletes_backward() -> None:
    vi = _mk()
    vi.cursor = 5  # on space between hello and world
    await vi._dispatch_normal_char("X")
    # X deletes the character before cursor (the 'o')
    assert vi.value == "hell world"
    assert vi.cursor == 4


async def test_p_pastes_after() -> None:
    vi = _mk()
    vi.cursor = 0
    # Yank by pressing y + w
    await vi._dispatch_normal_char("y")
    assert vi.mode == ViMode.OPERATOR_PENDING
    await vi._finish_operator("w")
    assert vi.mode == ViMode.NORMAL
    # Now paste
    vi.cursor = len(vi.value)
    await vi._dispatch_normal_char("p")
    assert vi.value == "hello worldhello "


async def test_D_deletes_to_end() -> None:
    vi = _mk()
    vi.cursor = 5
    await vi._dispatch_normal_char("D")
    assert vi.value == "hello"
    assert vi.cursor == 5


async def test_C_changes_to_end() -> None:
    vi = _mk()
    vi.cursor = 5
    await vi._dispatch_normal_char("C")
    assert vi.value == "hello"
    assert vi.cursor == 5
    assert vi.mode == ViMode.INSERT


# ── Operator + motion ──────────────────────────────────────────────────


async def test_dw_deletes_word() -> None:
    vi = _mk()
    vi.cursor = 0
    await vi._dispatch_normal_char("d")
    assert vi.mode == ViMode.OPERATOR_PENDING
    await vi._finish_operator("w")
    # dw with exclusive w motion deletes from cursor to start of next word
    assert vi.value == "world"
    assert vi.cursor == 0


async def test_yw_yanks_word() -> None:
    vi = _mk()
    vi.cursor = 0
    await vi._dispatch_normal_char("y")
    await vi._finish_operator("w")
    assert vi.value == "hello world"  # unchanged
    assert vi.cursor == 0
    assert vi._unnamed_register == "hello "


# ── Visual mode ────────────────────────────────────────────────────────


async def test_v_enters_visual() -> None:
    vi = _mk()
    await vi._dispatch_normal_char("v")
    assert vi.mode == ViMode.VISUAL
    assert vi._visual_anchor == vi.cursor


async def test_visual_range_computation() -> None:
    vi = _mk()
    vi.cursor = 5
    vi._mode = ViMode.VISUAL
    vi._visual_anchor = 0
    start, end = vi._visual_range()
    assert start == 0
    assert end == 6  # includes char at cursor


async def test_visual_delete_selection() -> None:
    vi = _mk()
    vi.cursor = 5
    vi._mode = ViMode.VISUAL
    vi._visual_anchor = 0
    # 'd' in visual mode triggers delete; 'd' won't match _decode_char so use direct event
    start, end = vi._visual_range()
    vi._op_exec(vi._op if vi._op else __import__("pana.tui.components.vi_input", fromlist=["Operator"]).Operator.DELETE, start, end)
    assert vi.value == "world"


# ── Insert mode editing ───────────────────────────────────────────────


async def test_insert_adds_text() -> None:
    vi = _mk()
    vi.cursor = 0  # move to start before entering insert
    await vi._dispatch_normal_char("i")
    await vi._input.handle_input("X")
    assert vi.value == "Xhello world"


async def test_append_appends_text() -> None:
    vi = _mk()
    vi.cursor = 5
    await vi._dispatch_normal_char("a")
    # Should have moved one right to append after 'o'
    assert vi.cursor == 6
    await vi._input.handle_input("Y")
    assert vi.value == "hello Yworld"


# ── Search ─────────────────────────────────────────────────────────────


async def test_n_repeats_last_search() -> None:
    vi = _mk()
    vi._last_search = "world"
    vi._last_search_forward = True
    vi.cursor = 0
    await vi._dispatch_normal_char("n")
    assert vi.cursor == 6


# ── Count prefix ───────────────────────────────────────────────────────


async def test_3x_deletes_three_chars() -> None:
    vi = _mk()
    vi.cursor = 0
    vi._count_str = "3"
    await vi._dispatch_normal_char("x")
    assert vi.value == "lo world"


async def test_2w_moves_two_words() -> None:
    vi = ViModeInput(initial_value="aaa bbb ccc", vi_mode_only=True)
    vi.cursor = 0
    vi._count_str = "2"
    await vi._dispatch_normal_char("w")
    # w from 0: skip "aaa " to "bbb ", skip "bbb " to "ccc"
    # positions: 0=a,1=a,2=a,3=space,4=b,5=b,6=b,7=space,8=c
    assert vi.cursor == 8  # start of "ccc"
