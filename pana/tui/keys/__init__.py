"""Keyboard input handling for terminal applications.

Supports legacy terminal input, Kitty keyboard protocol, and xterm
modifyOtherKeys sequences.
See: https://sw.kovidgoyal.net/kitty/keyboard-protocol/

API:
- matches_key(data, key_id) - Check if input matches a key identifier
- parse_key(data)          - Parse input and return the key identifier
- Key                     - Helper object for creating typed key identifiers
- set_enhanced_keyboard_protocol_active - Set global enhanced keyboard protocol state
- is_enhanced_keyboard_protocol_active  - Query global enhanced keyboard protocol state
"""

from __future__ import annotations

from pana.tui.keys.common import (
    Key,
    KeySpec,
    Modifier,
    ProtocolEvent,
    format_protocol_key_id,
    key_specs_equal,
    parse_key_spec,
)
from pana.tui.keys.legacy import (
    matches_legacy_named_key,
    matches_raw_printable,
    parse_legacy_named_key_id,
    parse_raw_printable_key_id,
)
from pana.tui.protocols.kitty.keyboard import (
    decode_kitty_printable,
    is_kitty_key_release,
    is_kitty_key_repeat,
    parse_kitty_event,
    parse_kitty_sequence,
)
from pana.tui.protocols.xterm.keyboard import (
    parse_xterm_modify_other_keys,
    parse_xterm_modify_other_keys_event,
)

_enhanced_keyboard_protocol_active = False



def set_enhanced_keyboard_protocol_active(active: bool) -> None:
    global _enhanced_keyboard_protocol_active
    _enhanced_keyboard_protocol_active = active



def is_enhanced_keyboard_protocol_active() -> bool:
    return _enhanced_keyboard_protocol_active



def _match_protocol_event(event: ProtocolEvent, key_spec: KeySpec) -> bool:
    protocol_key_id = format_protocol_key_id(event)
    if protocol_key_id is None:
        return False
    protocol_key_spec = parse_key_spec(protocol_key_id)
    return protocol_key_spec is not None and key_specs_equal(protocol_key_spec, key_spec)



def is_key_release(data: str) -> bool:
    """Return True if *data* is a Kitty key-release event."""
    return is_kitty_key_release(data)



def is_key_repeat(data: str) -> bool:
    """Return True if *data* is a Kitty key-repeat event."""
    return is_kitty_key_repeat(data)



def matches_key(data: str, key_id: str) -> bool:
    """Return True if *data* matches the key described by *key_id*.

    Examples: ``matches_key(data, "ctrl+c")``, ``matches_key(data, "shift+enter")``.
    """
    key_spec = parse_key_spec(key_id)
    if key_spec is None:
        return False

    kitty_event = parse_kitty_event(data)
    if kitty_event is not None:
        return _match_protocol_event(kitty_event, key_spec)

    xterm_event = parse_xterm_modify_other_keys_event(data)
    if xterm_event is not None:
        if len(key_spec.key) == 1 and key_spec.modifiers == Modifier(0):
            return False
        return _match_protocol_event(xterm_event, key_spec)

    if matches_legacy_named_key(data, key_spec, _enhanced_keyboard_protocol_active):
        return True

    return matches_raw_printable(data, key_spec, _enhanced_keyboard_protocol_active)



def parse_key(data: str) -> str | None:
    """Parse raw input and return a key identifier string, or None."""
    kitty_event = parse_kitty_event(data)
    if kitty_event is not None:
        return format_protocol_key_id(kitty_event)

    xterm_event = parse_xterm_modify_other_keys_event(data)
    if xterm_event is not None:
        return format_protocol_key_id(xterm_event)

    legacy_key_id = parse_legacy_named_key_id(data, _enhanced_keyboard_protocol_active)
    if legacy_key_id is not None:
        return legacy_key_id

    return parse_raw_printable_key_id(data, _enhanced_keyboard_protocol_active)


__all__ = [
    "Key",
    "decode_kitty_printable",
    "is_enhanced_keyboard_protocol_active",
    "is_key_release",
    "is_key_repeat",
    "matches_key",
    "parse_key",
    "parse_kitty_sequence",
    "parse_xterm_modify_other_keys",
    "set_enhanced_keyboard_protocol_active",
]
