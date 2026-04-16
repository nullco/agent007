"""Kitty keyboard protocol helpers and event parsers."""

from __future__ import annotations

import re
from typing import Final

from pana.tui.keys.common import (
    ARROW_CODEPOINTS,
    FUNCTIONAL_CODEPOINTS,
    LOCK_MASK,
    EventType,
    KittySequenceDict,
    Modifier,
    ProtocolEvent,
)
from pana.tui.protocols.kitty.sequences import (
    KITTY_KEYBOARD_DISABLE,
    KITTY_KEYBOARD_ENABLE,
    KITTY_KEYBOARD_QUERY,
    parse_kitty_keyboard_query_response,
)

_CSI_U_RE = re.compile(
    r"^\x1b\[(\d+)(?::(\d*))?(?::(\d+))?(?:;(\d+))?(?::(\d+))?u$"
)
_ARROW_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([ABCD])$")
_FUNC_MOD_RE = re.compile(r"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?~$")
_HOME_END_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([HF])$")

_KITTY_PRINTABLE_ALLOWED: Final = Modifier.SHIFT | LOCK_MASK



def _parse_event_type(value: str | None) -> EventType:
    if not value:
        return "press"
    parsed_value = int(value)
    if parsed_value == 2:
        return "repeat"
    if parsed_value == 3:
        return "release"
    return "press"



def parse_kitty_event(data: str) -> ProtocolEvent | None:
    match = _CSI_U_RE.match(data)
    if match:
        shifted_key = (
            int(match.group(2)) if match.group(2) and len(match.group(2)) > 0 else None
        )
        base_layout_key = int(match.group(3)) if match.group(3) else None
        modifier_value = int(match.group(4)) if match.group(4) else 1
        return ProtocolEvent(
            codepoint=int(match.group(1)),
            shifted_key=shifted_key,
            base_layout_key=base_layout_key,
            modifiers=Modifier(max(modifier_value - 1, 0)),
            event_type=_parse_event_type(match.group(5)),
        )

    match = _ARROW_MOD_RE.match(data)
    if match:
        arrow_map = {
            "A": ARROW_CODEPOINTS["up"],
            "B": ARROW_CODEPOINTS["down"],
            "C": ARROW_CODEPOINTS["right"],
            "D": ARROW_CODEPOINTS["left"],
        }
        modifier_value = int(match.group(1))
        return ProtocolEvent(
            codepoint=arrow_map[match.group(3)],
            modifiers=Modifier(max(modifier_value - 1, 0)),
            event_type=_parse_event_type(match.group(2)),
        )

    match = _FUNC_MOD_RE.match(data)
    if match:
        functional_map = {
            2: FUNCTIONAL_CODEPOINTS["insert"],
            3: FUNCTIONAL_CODEPOINTS["delete"],
            5: FUNCTIONAL_CODEPOINTS["pageUp"],
            6: FUNCTIONAL_CODEPOINTS["pageDown"],
            7: FUNCTIONAL_CODEPOINTS["home"],
            8: FUNCTIONAL_CODEPOINTS["end"],
        }
        codepoint = functional_map.get(int(match.group(1)))
        if codepoint is None:
            return None
        modifier_value = int(match.group(2)) if match.group(2) else 1
        return ProtocolEvent(
            codepoint=codepoint,
            modifiers=Modifier(max(modifier_value - 1, 0)),
            event_type=_parse_event_type(match.group(3)),
        )

    match = _HOME_END_MOD_RE.match(data)
    if match:
        key_name = "home" if match.group(3) == "H" else "end"
        modifier_value = int(match.group(1))
        return ProtocolEvent(
            codepoint=FUNCTIONAL_CODEPOINTS[key_name],
            modifiers=Modifier(max(modifier_value - 1, 0)),
            event_type=_parse_event_type(match.group(2)),
        )

    return None



def parse_kitty_sequence(data: str) -> KittySequenceDict | None:
    event = parse_kitty_event(data)
    if event is None:
        return None
    return {
        "codepoint": event.codepoint,
        "shifted_key": event.shifted_key,
        "base_layout_key": event.base_layout_key,
        "modifier": int(event.modifiers),
        "event_type": event.event_type,
    }



def decode_kitty_printable(data: str) -> str | None:
    """Extract a printable character from a Kitty CSI-u sequence, or None."""
    event = parse_kitty_event(data)
    if event is None:
        return None

    if event.modifiers & ~_KITTY_PRINTABLE_ALLOWED:
        return None
    if event.modifiers & (Modifier.ALT | Modifier.CTRL):
        return None

    effective_codepoint = event.codepoint
    if event.modifiers & Modifier.SHIFT and event.shifted_key is not None:
        effective_codepoint = event.shifted_key
    if effective_codepoint < 32:
        return None

    try:
        return chr(effective_codepoint)
    except (OverflowError, ValueError):
        return None



def is_kitty_key_release(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    event = parse_kitty_event(data)
    return event is not None and event.event_type == "release"



def is_kitty_key_repeat(data: str) -> bool:
    if "\x1b[200~" in data:
        return False
    event = parse_kitty_event(data)
    return event is not None and event.event_type == "repeat"


__all__ = [
    "KITTY_KEYBOARD_DISABLE",
    "KITTY_KEYBOARD_ENABLE",
    "KITTY_KEYBOARD_QUERY",
    "decode_kitty_printable",
    "is_kitty_key_release",
    "is_kitty_key_repeat",
    "parse_kitty_event",
    "parse_kitty_keyboard_query_response",
    "parse_kitty_sequence",
]
