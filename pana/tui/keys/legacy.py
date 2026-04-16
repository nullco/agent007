"""Legacy terminal key parsing and raw printable matching."""

from __future__ import annotations

import os
from typing import Final

from pana.tui.keys.common import (
    SYMBOL_KEYS,
    KeySpec,
    Modifier,
    format_key_id,
    is_ascii_digit,
    is_latin_lower,
    key_specs_equal,
    parse_key_spec,
    raw_ctrl_char,
)

LEGACY_KEY_SEQUENCES: Final[dict[str, list[str]]] = {
    "up": ["\x1b[A", "\x1bOA"],
    "down": ["\x1b[B", "\x1bOB"],
    "right": ["\x1b[C", "\x1bOC"],
    "left": ["\x1b[D", "\x1bOD"],
    "home": ["\x1b[H", "\x1bOH", "\x1b[1~", "\x1b[7~"],
    "end": ["\x1b[F", "\x1bOF", "\x1b[4~", "\x1b[8~"],
    "insert": ["\x1b[2~"],
    "delete": ["\x1b[3~"],
    "pageUp": ["\x1b[5~", "\x1b[[5~"],
    "pageDown": ["\x1b[6~", "\x1b[[6~"],
    "clear": ["\x1b[E", "\x1bOE"],
    "f1": ["\x1bOP", "\x1b[11~", "\x1b[[A"],
    "f2": ["\x1bOQ", "\x1b[12~", "\x1b[[B"],
    "f3": ["\x1bOR", "\x1b[13~", "\x1b[[C"],
    "f4": ["\x1bOS", "\x1b[14~", "\x1b[[D"],
    "f5": ["\x1b[15~", "\x1b[[E"],
    "f6": ["\x1b[17~"],
    "f7": ["\x1b[18~"],
    "f8": ["\x1b[19~"],
    "f9": ["\x1b[20~"],
    "f10": ["\x1b[21~"],
    "f11": ["\x1b[23~"],
    "f12": ["\x1b[24~"],
}

LEGACY_SHIFT_SEQUENCES: Final[dict[str, list[str]]] = {
    "up": ["\x1b[a"],
    "down": ["\x1b[b"],
    "right": ["\x1b[c"],
    "left": ["\x1b[d"],
    "clear": ["\x1b[e"],
    "insert": ["\x1b[2$"],
    "delete": ["\x1b[3$"],
    "pageUp": ["\x1b[5$"],
    "pageDown": ["\x1b[6$"],
    "home": ["\x1b[7$"],
    "end": ["\x1b[8$"],
}

LEGACY_CTRL_SEQUENCES: Final[dict[str, list[str]]] = {
    "up": ["\x1bOa"],
    "down": ["\x1bOb"],
    "right": ["\x1bOc"],
    "left": ["\x1bOd"],
    "clear": ["\x1bOe"],
    "insert": ["\x1b[2^"],
    "delete": ["\x1b[3^"],
    "pageUp": ["\x1b[5^"],
    "pageDown": ["\x1b[6^"],
    "home": ["\x1b[7^"],
    "end": ["\x1b[8^"],
}

_SPECIAL_LEGACY_KEY_IDS: Final = {
    "\x1b": "escape",
    "\x1c": "ctrl+\\",
    "\x1d": "ctrl+]",
    "\x1f": "ctrl+-",
    "\x1b\x1b": "ctrl+alt+[",
    "\x1b\x1c": "ctrl+alt+\\",
    "\x1b\x1d": "ctrl+alt+]",
    "\x1b\x1f": "ctrl+alt+-",
    "\t": "tab",
    "\x00": "ctrl+space",
    " ": "space",
    "\x7f": "backspace",
    "\x1b[Z": "shift+tab",
}


def _build_legacy_sequence_key_ids() -> dict[str, str]:
    sequence_key_ids: dict[str, str] = {}

    for key_name, sequences in LEGACY_KEY_SEQUENCES.items():
        for sequence in sequences:
            sequence_key_ids[sequence] = key_name

    for key_name, sequences in LEGACY_SHIFT_SEQUENCES.items():
        key_id = format_key_id(key_name, Modifier.SHIFT)
        if key_id is None:
            continue
        for sequence in sequences:
            sequence_key_ids[sequence] = key_id

    for key_name, sequences in LEGACY_CTRL_SEQUENCES.items():
        key_id = format_key_id(key_name, Modifier.CTRL)
        if key_id is None:
            continue
        for sequence in sequences:
            sequence_key_ids[sequence] = key_id

    sequence_key_ids.update(
        {
            "\x1bb": "alt+left",
            "\x1bf": "alt+right",
            "\x1bp": "alt+up",
            "\x1bn": "alt+down",
        }
    )
    return sequence_key_ids


LEGACY_SEQUENCE_KEY_IDS: Final = _build_legacy_sequence_key_ids()



def is_windows_terminal_session() -> bool:
    """Return True when running inside Windows Terminal, but not over SSH."""
    return (
        bool(os.environ.get("WT_SESSION"))
        and not os.environ.get("SSH_CONNECTION")
        and not os.environ.get("SSH_CLIENT")
        and not os.environ.get("SSH_TTY")
    )



def parse_legacy_named_key_id(data: str, enhanced_keyboard_protocol_active: bool) -> str | None:
    if enhanced_keyboard_protocol_active and data in ("\x1b\r", "\n"):
        return "shift+enter"

    if data in _SPECIAL_LEGACY_KEY_IDS:
        return _SPECIAL_LEGACY_KEY_IDS[data]

    if data == "\r" or (
        not enhanced_keyboard_protocol_active and data == "\n"
    ) or data == "\x1bOM":
        return "enter"

    if not enhanced_keyboard_protocol_active and data == "\x1b\r":
        return "alt+enter"

    if not enhanced_keyboard_protocol_active and data == "\x1b ":
        return "alt+space"

    if data in ("\x1b\x7f", "\x1b\x08"):
        return "alt+backspace"

    if data == "\x08":
        return "ctrl+backspace" if is_windows_terminal_session() else "backspace"

    if not enhanced_keyboard_protocol_active and data == "\x1bB":
        return "alt+left"

    if not enhanced_keyboard_protocol_active and data == "\x1bF":
        return "alt+right"

    return LEGACY_SEQUENCE_KEY_IDS.get(data)



def parse_raw_printable_key_id(data: str, enhanced_keyboard_protocol_active: bool) -> str | None:
    if not enhanced_keyboard_protocol_active and len(data) == 2 and data[0] == "\x1b":
        codepoint = ord(data[1])
        if 1 <= codepoint <= 26:
            return f"ctrl+alt+{chr(codepoint + 96)}"
        if is_latin_lower(codepoint) or is_ascii_digit(codepoint):
            return f"alt+{chr(codepoint)}"

    if len(data) != 1:
        return None

    codepoint = ord(data)
    if 1 <= codepoint <= 26:
        return f"ctrl+{chr(codepoint + 96)}"
    if 32 <= codepoint <= 126:
        return data
    return None



def matches_raw_printable(
    data: str,
    key_spec: KeySpec,
    enhanced_keyboard_protocol_active: bool,
) -> bool:
    key_name = key_spec.key
    modifiers = key_spec.modifiers

    if len(key_name) != 1 or not (
        ("a" <= key_name <= "z") or ("0" <= key_name <= "9") or key_name in SYMBOL_KEYS
    ):
        return False

    raw_ctrl_character = raw_ctrl_char(key_name)
    is_letter = "a" <= key_name <= "z"
    is_letter_or_digit = is_letter or ("0" <= key_name <= "9")

    if (
        modifiers == Modifier.CTRL | Modifier.ALT
        and not enhanced_keyboard_protocol_active
        and raw_ctrl_character is not None
    ):
        return data == f"\x1b{raw_ctrl_character}"

    if (
        modifiers == Modifier.ALT
        and not enhanced_keyboard_protocol_active
        and is_letter_or_digit
    ):
        return data == f"\x1b{key_name}"

    if modifiers == Modifier.CTRL:
        return raw_ctrl_character is not None and data == raw_ctrl_character

    if modifiers == Modifier.SHIFT:
        return is_letter and data == key_name.upper()

    if modifiers == Modifier(0):
        return data == key_name

    return False



def matches_legacy_named_key(
    data: str,
    key_spec: KeySpec,
    enhanced_keyboard_protocol_active: bool,
) -> bool:
    legacy_key_id = parse_legacy_named_key_id(data, enhanced_keyboard_protocol_active)
    if legacy_key_id is None:
        return False
    legacy_key_spec = parse_key_spec(legacy_key_id)
    return legacy_key_spec is not None and key_specs_equal(legacy_key_spec, key_spec)
