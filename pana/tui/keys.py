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

import os
import re
from dataclasses import dataclass
from enum import IntFlag
from typing import Final, Literal, TypedDict

_enhanced_keyboard_protocol_active = False


class _Key:
    # Special keys
    escape = "escape"
    esc = "esc"
    enter = "enter"
    return_ = "return"
    tab = "tab"
    space = "space"
    backspace = "backspace"
    delete = "delete"
    insert = "insert"
    clear = "clear"
    home = "home"
    end = "end"
    page_up = "pageUp"
    page_down = "pageDown"
    up = "up"
    down = "down"
    left = "left"
    right = "right"
    f1 = "f1"
    f2 = "f2"
    f3 = "f3"
    f4 = "f4"
    f5 = "f5"
    f6 = "f6"
    f7 = "f7"
    f8 = "f8"
    f9 = "f9"
    f10 = "f10"
    f11 = "f11"
    f12 = "f12"

    # Symbol keys
    backtick = "`"
    hyphen = "-"
    equals = "="
    leftbracket = "["
    rightbracket = "]"
    backslash = "\\"
    semicolon = ";"
    quote = "'"
    comma = ","
    period = "."
    slash = "/"

    @staticmethod
    def ctrl(key: str) -> str:
        return f"ctrl+{key}"

    @staticmethod
    def shift(key: str) -> str:
        return f"shift+{key}"

    @staticmethod
    def alt(key: str) -> str:
        return f"alt+{key}"

    @staticmethod
    def ctrl_shift(key: str) -> str:
        return f"ctrl+shift+{key}"

    @staticmethod
    def shift_ctrl(key: str) -> str:
        return f"shift+ctrl+{key}"

    @staticmethod
    def ctrl_alt(key: str) -> str:
        return f"ctrl+alt+{key}"

    @staticmethod
    def shift_alt(key: str) -> str:
        return f"shift+alt+{key}"

    @staticmethod
    def ctrl_shift_alt(key: str) -> str:
        return f"ctrl+shift+alt+{key}"


Key = _Key()


class Modifier(IntFlag):
    """Bitmask for supported keyboard modifiers."""

    SHIFT = 1
    ALT = 2
    CTRL = 4
    CAPS_LOCK = 64
    NUM_LOCK = 128


LOCK_MASK: Final = Modifier.CAPS_LOCK | Modifier.NUM_LOCK
SUPPORTED_MODIFIERS: Final = Modifier.SHIFT | Modifier.ALT | Modifier.CTRL
SYMBOL_KEYS: Final = set("`-=[]\\;',./!@#$%^&*()_+|~{}:<>?")

CODEPOINTS: Final = {
    "escape": 27,
    "tab": 9,
    "enter": 13,
    "space": 32,
    "backspace": 127,
    "kpEnter": 57414,
}

ARROW_CODEPOINTS: Final = {"up": -1, "down": -2, "right": -3, "left": -4}

FUNCTIONAL_CODEPOINTS: Final = {
    "delete": -10,
    "insert": -11,
    "pageUp": -12,
    "pageDown": -13,
    "home": -14,
    "end": -15,
}

CODEPOINT_TO_KEY_NAME: Final = {
    CODEPOINTS["escape"]: "escape",
    CODEPOINTS["tab"]: "tab",
    CODEPOINTS["enter"]: "enter",
    CODEPOINTS["kpEnter"]: "enter",
    CODEPOINTS["space"]: "space",
    CODEPOINTS["backspace"]: "backspace",
    FUNCTIONAL_CODEPOINTS["delete"]: "delete",
    FUNCTIONAL_CODEPOINTS["insert"]: "insert",
    FUNCTIONAL_CODEPOINTS["home"]: "home",
    FUNCTIONAL_CODEPOINTS["end"]: "end",
    FUNCTIONAL_CODEPOINTS["pageUp"]: "pageUp",
    FUNCTIONAL_CODEPOINTS["pageDown"]: "pageDown",
    ARROW_CODEPOINTS["up"]: "up",
    ARROW_CODEPOINTS["down"]: "down",
    ARROW_CODEPOINTS["left"]: "left",
    ARROW_CODEPOINTS["right"]: "right",
}

NAMED_KEY_CODEPOINTS: Final = {
    **{name: codepoint for name, codepoint in CODEPOINTS.items() if name != "kpEnter"},
    **ARROW_CODEPOINTS,
    **FUNCTIONAL_CODEPOINTS,
}

NORMALIZED_KEY_ALIASES: Final = {
    "esc": "escape",
    "return": "enter",
    "pageup": "pageUp",
    "pagedown": "pageDown",
}

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


_CSI_U_RE = re.compile(
    r"^\x1b\[(\d+)(?::(\d*))?(?::(\d+))?(?:;(\d+))?(?::(\d+))?u$"
)
_ARROW_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([ABCD])$")
_FUNC_MOD_RE = re.compile(r"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?~$")
_HOME_END_MOD_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([HF])$")
_MODIFY_OTHER_RE = re.compile(r"^\x1b\[27;(\d+);(\d+)~$")


EventType = Literal["press", "repeat", "release"]


class KittySequenceDict(TypedDict):
    codepoint: int
    shifted_key: int | None
    base_layout_key: int | None
    modifier: int
    event_type: EventType


class ModifyOtherKeysDict(TypedDict):
    codepoint: int
    modifier: int


@dataclass(frozen=True)
class KeySpec:
    key: str
    modifiers: Modifier


@dataclass(frozen=True)
class ProtocolEvent:
    codepoint: int
    modifiers: Modifier
    event_type: EventType
    shifted_key: int | None = None
    base_layout_key: int | None = None


def set_enhanced_keyboard_protocol_active(active: bool) -> None:
    global _enhanced_keyboard_protocol_active
    _enhanced_keyboard_protocol_active = active



def is_enhanced_keyboard_protocol_active() -> bool:
    return _enhanced_keyboard_protocol_active



def _normalize_key_name(key: str) -> str:
    return NORMALIZED_KEY_ALIASES.get(key.lower(), key.lower())



def _modifiers_to_key_id_prefix(modifiers: Modifier) -> str | None:
    effective = modifiers & ~LOCK_MASK
    if effective & ~SUPPORTED_MODIFIERS:
        return None

    parts: list[str] = []
    if effective & Modifier.SHIFT:
        parts.append("shift")
    if effective & Modifier.CTRL:
        parts.append("ctrl")
    if effective & Modifier.ALT:
        parts.append("alt")
    return "+".join(parts)



def _format_key_id(key: str, modifiers: Modifier) -> str | None:
    prefix = _modifiers_to_key_id_prefix(modifiers)
    if prefix is None:
        return None
    return f"{prefix}+{key}" if prefix else key



def _build_legacy_sequence_key_ids() -> dict[str, str]:
    sequence_key_ids: dict[str, str] = {}

    for key_name, sequences in LEGACY_KEY_SEQUENCES.items():
        for sequence in sequences:
            sequence_key_ids[sequence] = key_name

    for key_name, sequences in LEGACY_SHIFT_SEQUENCES.items():
        key_id = _format_key_id(key_name, Modifier.SHIFT)
        if key_id is None:
            continue
        for sequence in sequences:
            sequence_key_ids[sequence] = key_id

    for key_name, sequences in LEGACY_CTRL_SEQUENCES.items():
        key_id = _format_key_id(key_name, Modifier.CTRL)
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



def _is_windows_terminal_session() -> bool:
    """Return True when running inside Windows Terminal, but not over SSH."""
    return (
        bool(os.environ.get("WT_SESSION"))
        and not os.environ.get("SSH_CONNECTION")
        and not os.environ.get("SSH_CLIENT")
        and not os.environ.get("SSH_TTY")
    )



def _parse_event_type(value: str | None) -> EventType:
    if not value:
        return "press"
    parsed_value = int(value)
    if parsed_value == 2:
        return "repeat"
    if parsed_value == 3:
        return "release"
    return "press"



def _parse_kitty_event(data: str) -> ProtocolEvent | None:
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
    event = _parse_kitty_event(data)
    if event is None:
        return None
    return {
        "codepoint": event.codepoint,
        "shifted_key": event.shifted_key,
        "base_layout_key": event.base_layout_key,
        "modifier": int(event.modifiers),
        "event_type": event.event_type,
    }



def _parse_xterm_modify_other_keys_event(data: str) -> ProtocolEvent | None:
    match = _MODIFY_OTHER_RE.match(data)
    if not match:
        return None
    return ProtocolEvent(
        codepoint=int(match.group(2)),
        modifiers=Modifier(max(int(match.group(1)) - 1, 0)),
        event_type="press",
    )



def _parse_xterm_modify_other_keys(data: str) -> ModifyOtherKeysDict | None:
    event = _parse_xterm_modify_other_keys_event(data)
    if event is None:
        return None
    return {"codepoint": event.codepoint, "modifier": int(event.modifiers)}



def _is_latin_lower(codepoint: int) -> bool:
    return 97 <= codepoint <= 122



def _is_ascii_digit(codepoint: int) -> bool:
    return 48 <= codepoint <= 57



def _is_symbol_codepoint(codepoint: int) -> bool:
    return 0 <= codepoint <= 0x10FFFF and chr(codepoint) in SYMBOL_KEYS



def _effective_codepoint_for_key_name(
    codepoint: int,
    base_layout_key: int | None,
) -> int:
    if _is_latin_lower(codepoint) or _is_ascii_digit(codepoint) or _is_symbol_codepoint(codepoint):
        return codepoint
    if base_layout_key is not None:
        return base_layout_key
    return codepoint



def _key_name_from_codepoint(
    codepoint: int,
    base_layout_key: int | None = None,
) -> str | None:
    effective_codepoint = _effective_codepoint_for_key_name(codepoint, base_layout_key)
    key_name = CODEPOINT_TO_KEY_NAME.get(effective_codepoint)
    if key_name is not None:
        return key_name
    if _is_ascii_digit(effective_codepoint) or _is_latin_lower(effective_codepoint):
        return chr(effective_codepoint)
    if _is_symbol_codepoint(effective_codepoint):
        return chr(effective_codepoint)
    return None



def _format_protocol_key_id(event: ProtocolEvent) -> str | None:
    key_name = _key_name_from_codepoint(event.codepoint, event.base_layout_key)
    if key_name is None:
        return None
    return _format_key_id(key_name, event.modifiers)



def _parse_key_spec(key_id: str) -> KeySpec | None:
    parts = [part for part in key_id.lower().split("+") if part]
    if not parts:
        return None

    key_name = _normalize_key_name(parts[-1])
    modifiers = Modifier(0)
    for modifier_name in parts[:-1]:
        if modifier_name == "shift":
            modifiers |= Modifier.SHIFT
            continue
        if modifier_name == "alt":
            modifiers |= Modifier.ALT
            continue
        if modifier_name == "ctrl":
            modifiers |= Modifier.CTRL
            continue
        return None
    return KeySpec(key=key_name, modifiers=modifiers)



def _key_specs_equal(left: KeySpec, right: KeySpec) -> bool:
    return left.key == right.key and left.modifiers == right.modifiers



def _parse_legacy_named_key_id(data: str) -> str | None:
    if _enhanced_keyboard_protocol_active and data in ("\x1b\r", "\n"):
        return "shift+enter"

    if data in _SPECIAL_LEGACY_KEY_IDS:
        return _SPECIAL_LEGACY_KEY_IDS[data]

    if data == "\r" or (
        not _enhanced_keyboard_protocol_active and data == "\n"
    ) or data == "\x1bOM":
        return "enter"

    if not _enhanced_keyboard_protocol_active and data == "\x1b\r":
        return "alt+enter"

    if not _enhanced_keyboard_protocol_active and data == "\x1b ":
        return "alt+space"

    if data in ("\x1b\x7f", "\x1b\x08"):
        return "alt+backspace"

    if data == "\x08":
        return "ctrl+backspace" if _is_windows_terminal_session() else "backspace"

    if not _enhanced_keyboard_protocol_active and data == "\x1bB":
        return "alt+left"

    if not _enhanced_keyboard_protocol_active and data == "\x1bF":
        return "alt+right"

    return LEGACY_SEQUENCE_KEY_IDS.get(data)



def _parse_raw_printable_key_id(data: str) -> str | None:
    if not _enhanced_keyboard_protocol_active and len(data) == 2 and data[0] == "\x1b":
        codepoint = ord(data[1])
        if 1 <= codepoint <= 26:
            return f"ctrl+alt+{chr(codepoint + 96)}"
        if _is_latin_lower(codepoint) or _is_ascii_digit(codepoint):
            return f"alt+{chr(codepoint)}"

    if len(data) != 1:
        return None

    codepoint = ord(data)
    if 1 <= codepoint <= 26:
        return f"ctrl+{chr(codepoint + 96)}"
    if 32 <= codepoint <= 126:
        return data
    return None



def _raw_ctrl_char(key_name: str) -> str | None:
    lower_key_name = key_name.lower()
    codepoint = ord(lower_key_name)
    if _is_latin_lower(codepoint) or lower_key_name in ("[", "\\", "]", "_"):
        return chr(codepoint & 0x1F)
    if lower_key_name == "-":
        return chr(31)
    return None



def _match_protocol_event(event: ProtocolEvent, key_spec: KeySpec) -> bool:
    protocol_key_id = _format_protocol_key_id(event)
    if protocol_key_id is None:
        return False
    protocol_key_spec = _parse_key_spec(protocol_key_id)
    return protocol_key_spec is not None and _key_specs_equal(protocol_key_spec, key_spec)



def _matches_raw_printable(data: str, key_spec: KeySpec) -> bool:
    key_name = key_spec.key
    modifiers = key_spec.modifiers

    if len(key_name) != 1 or not (
        ("a" <= key_name <= "z") or ("0" <= key_name <= "9") or key_name in SYMBOL_KEYS
    ):
        return False

    raw_ctrl_character = _raw_ctrl_char(key_name)
    is_letter = "a" <= key_name <= "z"
    is_letter_or_digit = is_letter or ("0" <= key_name <= "9")

    if (
        modifiers == Modifier.CTRL | Modifier.ALT
        and not _enhanced_keyboard_protocol_active
        and raw_ctrl_character is not None
    ):
        return data == f"\x1b{raw_ctrl_character}"

    if (
        modifiers == Modifier.ALT
        and not _enhanced_keyboard_protocol_active
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



def is_key_release(data: str) -> bool:
    """Return True if *data* is a Kitty key-release event."""
    if "\x1b[200~" in data:
        return False
    event = _parse_kitty_event(data)
    return event is not None and event.event_type == "release"



def is_key_repeat(data: str) -> bool:
    """Return True if *data* is a Kitty key-repeat event."""
    if "\x1b[200~" in data:
        return False
    event = _parse_kitty_event(data)
    return event is not None and event.event_type == "repeat"



def matches_key(data: str, key_id: str) -> bool:
    """Return True if *data* matches the key described by *key_id*.

    Examples: ``matches_key(data, "ctrl+c")``, ``matches_key(data, "shift+enter")``.
    """
    key_spec = _parse_key_spec(key_id)
    if key_spec is None:
        return False

    kitty_event = _parse_kitty_event(data)
    if kitty_event is not None:
        return _match_protocol_event(kitty_event, key_spec)

    xterm_event = _parse_xterm_modify_other_keys_event(data)
    if xterm_event is not None:
        if len(key_spec.key) == 1 and key_spec.modifiers == Modifier(0):
            return False
        return _match_protocol_event(xterm_event, key_spec)

    legacy_key_id = _parse_legacy_named_key_id(data)
    if legacy_key_id is not None:
        legacy_key_spec = _parse_key_spec(legacy_key_id)
        return legacy_key_spec is not None and _key_specs_equal(legacy_key_spec, key_spec)

    return _matches_raw_printable(data, key_spec)



def parse_key(data: str) -> str | None:
    """Parse raw input and return a key identifier string, or None."""
    kitty_event = _parse_kitty_event(data)
    if kitty_event is not None:
        return _format_protocol_key_id(kitty_event)

    xterm_event = _parse_xterm_modify_other_keys_event(data)
    if xterm_event is not None:
        return _format_protocol_key_id(xterm_event)

    legacy_key_id = _parse_legacy_named_key_id(data)
    if legacy_key_id is not None:
        return legacy_key_id

    return _parse_raw_printable_key_id(data)


_KITTY_PRINTABLE_ALLOWED: Final = Modifier.SHIFT | LOCK_MASK



def decode_kitty_printable(data: str) -> str | None:
    """Extract a printable character from a Kitty CSI-u sequence, or None."""
    event = _parse_kitty_event(data)
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
