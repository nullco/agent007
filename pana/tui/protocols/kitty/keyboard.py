"""Kitty keyboard protocol lifecycle management."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import Enum

from pana.tui.keys import set_kitty_protocol_active
from pana.tui.protocols.kitty.sequences import (
    KITTY_KEYBOARD_DISABLE,
    KITTY_KEYBOARD_ENABLE,
    KITTY_KEYBOARD_QUERY,
    MODIFY_OTHER_KEYS_OFF,
    MODIFY_OTHER_KEYS_ON,
    parse_kitty_keyboard_query_response,
)


class KeyboardProtocolMode(str, Enum):
    """Active keyboard input mode for the terminal."""

    LEGACY = "legacy"
    PROBING = "probing"
    KITTY = "kitty"
    MODIFY_OTHER_KEYS = "modify_other_keys"


class KittyKeyboardProtocolController:
    """Own Kitty keyboard negotiation and xterm fallback lifecycle."""

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._mode = KeyboardProtocolMode.LEGACY
        self._fallback_handle: asyncio.TimerHandle | None = None

    @property
    def mode(self) -> KeyboardProtocolMode:
        return self._mode

    @property
    def is_active(self) -> bool:
        return self._mode is KeyboardProtocolMode.KITTY

    def start(self) -> None:
        """Start Kitty support probing and schedule modifyOtherKeys fallback."""
        self.stop()
        self._mode = KeyboardProtocolMode.PROBING
        set_kitty_protocol_active(False)
        self._write(KITTY_KEYBOARD_QUERY)
        loop = asyncio.get_running_loop()
        self._fallback_handle = loop.call_later(0.15, self._activate_modify_other_keys)

    def stop(self) -> None:
        """Disable any negotiated keyboard enhancements and cancel probing."""
        self._cancel_fallback()

        if self._mode is KeyboardProtocolMode.KITTY:
            self._write(KITTY_KEYBOARD_DISABLE)
        elif self._mode is KeyboardProtocolMode.MODIFY_OTHER_KEYS:
            self._write(MODIFY_OTHER_KEYS_OFF)

        self._mode = KeyboardProtocolMode.LEGACY
        set_kitty_protocol_active(False)

    def handle_input(self, data: str) -> bool:
        """Consume Kitty keyboard negotiation responses.

        Returns True when *data* is a consumed protocol response.
        """
        flags = parse_kitty_keyboard_query_response(data)
        if flags is None:
            return False

        if self._mode in (
            KeyboardProtocolMode.PROBING,
            KeyboardProtocolMode.MODIFY_OTHER_KEYS,
        ):
            self._activate_kitty_protocol()
        return True

    def _activate_kitty_protocol(self) -> None:
        self._cancel_fallback()

        if self._mode is KeyboardProtocolMode.MODIFY_OTHER_KEYS:
            self._write(MODIFY_OTHER_KEYS_OFF)

        self._write(KITTY_KEYBOARD_ENABLE)
        self._mode = KeyboardProtocolMode.KITTY
        set_kitty_protocol_active(True)

    def _activate_modify_other_keys(self) -> None:
        self._fallback_handle = None
        if self._mode is not KeyboardProtocolMode.PROBING:
            return
        self._write(MODIFY_OTHER_KEYS_ON)
        self._mode = KeyboardProtocolMode.MODIFY_OTHER_KEYS

    def _cancel_fallback(self) -> None:
        if self._fallback_handle is None:
            return
        self._fallback_handle.cancel()
        self._fallback_handle = None
