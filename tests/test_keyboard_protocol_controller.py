from __future__ import annotations

import asyncio

import pytest

from pana.tui.keys import (
    is_enhanced_keyboard_protocol_active,
    set_enhanced_keyboard_protocol_active,
)
from pana.tui.protocols.keyboard import KeyboardProtocolController, KeyboardProtocolMode
from pana.tui.protocols.kitty import (
    KITTY_KEYBOARD_DISABLE,
    KITTY_KEYBOARD_ENABLE,
    KITTY_KEYBOARD_QUERY,
)
from pana.tui.protocols.xterm import MODIFY_OTHER_KEYS_OFF, MODIFY_OTHER_KEYS_ON


@pytest.fixture(autouse=True)
def _reset_enhanced_keyboard_state() -> None:
    set_enhanced_keyboard_protocol_active(False)
    yield
    set_enhanced_keyboard_protocol_active(False)


async def test_falls_back_to_modify_other_keys_when_kitty_probe_times_out() -> None:
    writes: list[str] = []
    controller = KeyboardProtocolController(writes.append)

    controller.start()

    assert writes == [KITTY_KEYBOARD_QUERY]
    assert controller.mode is KeyboardProtocolMode.PROBING
    assert not is_enhanced_keyboard_protocol_active()

    await asyncio.sleep(0.2)

    assert writes == [KITTY_KEYBOARD_QUERY, MODIFY_OTHER_KEYS_ON]
    assert controller.mode is KeyboardProtocolMode.MODIFY_OTHER_KEYS
    assert not is_enhanced_keyboard_protocol_active()

    controller.stop()

    assert writes == [KITTY_KEYBOARD_QUERY, MODIFY_OTHER_KEYS_ON, MODIFY_OTHER_KEYS_OFF]
    assert controller.mode is KeyboardProtocolMode.LEGACY
    assert not is_enhanced_keyboard_protocol_active()


async def test_activates_kitty_without_emitting_xterm_fallback() -> None:
    writes: list[str] = []
    controller = KeyboardProtocolController(writes.append)

    controller.start()

    consumed = controller.handle_input("\x1b[?1u")

    assert consumed
    assert writes == [KITTY_KEYBOARD_QUERY, KITTY_KEYBOARD_ENABLE]
    assert controller.mode is KeyboardProtocolMode.KITTY
    assert is_enhanced_keyboard_protocol_active()

    await asyncio.sleep(0.2)

    assert writes == [KITTY_KEYBOARD_QUERY, KITTY_KEYBOARD_ENABLE]

    controller.stop()

    assert writes == [KITTY_KEYBOARD_QUERY, KITTY_KEYBOARD_ENABLE, KITTY_KEYBOARD_DISABLE]
    assert controller.mode is KeyboardProtocolMode.LEGACY
    assert not is_enhanced_keyboard_protocol_active()


async def test_switches_from_xterm_fallback_to_kitty_when_response_arrives_late() -> None:
    writes: list[str] = []
    controller = KeyboardProtocolController(writes.append)

    controller.start()
    await asyncio.sleep(0.2)

    consumed = controller.handle_input("\x1b[?3u")

    assert consumed
    assert writes == [
        KITTY_KEYBOARD_QUERY,
        MODIFY_OTHER_KEYS_ON,
        MODIFY_OTHER_KEYS_OFF,
        KITTY_KEYBOARD_ENABLE,
    ]
    assert controller.mode is KeyboardProtocolMode.KITTY
    assert is_enhanced_keyboard_protocol_active()

    controller.stop()

    assert writes == [
        KITTY_KEYBOARD_QUERY,
        MODIFY_OTHER_KEYS_ON,
        MODIFY_OTHER_KEYS_OFF,
        KITTY_KEYBOARD_ENABLE,
        KITTY_KEYBOARD_DISABLE,
    ]


def test_protocol_exports_keep_kitty_and_xterm_separate() -> None:
    import pana.tui.protocols.keyboard as keyboard
    import pana.tui.protocols.kitty as kitty
    import pana.tui.protocols.xterm as xterm

    assert hasattr(keyboard, "KeyboardProtocolController")
    assert hasattr(keyboard, "KeyboardProtocolMode")
    assert hasattr(kitty, "KITTY_KEYBOARD_QUERY")
    assert not hasattr(kitty, "MODIFY_OTHER_KEYS_ON")
    assert not hasattr(kitty, "KeyboardProtocolController")
    assert hasattr(xterm, "MODIFY_OTHER_KEYS_ON")
    assert hasattr(xterm, "MODIFY_OTHER_KEYS_OFF")
