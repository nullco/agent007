"""Shared models and helpers for keyboard input parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import Final, Literal, TypedDict


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

NORMALIZED_KEY_ALIASES: Final = {
    "esc": "escape",
    "return": "enter",
    "pageup": "pageUp",
    "pagedown": "pageDown",
}


def normalize_key_name(key: str) -> str:
    return NORMALIZED_KEY_ALIASES.get(key.lower(), key.lower())



def modifiers_to_key_id_prefix(modifiers: Modifier) -> str | None:
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



def format_key_id(key: str, modifiers: Modifier) -> str | None:
    prefix = modifiers_to_key_id_prefix(modifiers)
    if prefix is None:
        return None
    return f"{prefix}+{key}" if prefix else key



def is_latin_lower(codepoint: int) -> bool:
    return 97 <= codepoint <= 122



def is_ascii_digit(codepoint: int) -> bool:
    return 48 <= codepoint <= 57



def is_symbol_codepoint(codepoint: int) -> bool:
    return 0 <= codepoint <= 0x10FFFF and chr(codepoint) in SYMBOL_KEYS



def effective_codepoint_for_key_name(
    codepoint: int,
    base_layout_key: int | None,
) -> int:
    if (
        is_latin_lower(codepoint)
        or is_ascii_digit(codepoint)
        or is_symbol_codepoint(codepoint)
    ):
        return codepoint
    if base_layout_key is not None:
        return base_layout_key
    return codepoint



def key_name_from_codepoint(
    codepoint: int,
    base_layout_key: int | None = None,
) -> str | None:
    effective_codepoint = effective_codepoint_for_key_name(codepoint, base_layout_key)
    key_name = CODEPOINT_TO_KEY_NAME.get(effective_codepoint)
    if key_name is not None:
        return key_name
    if is_ascii_digit(effective_codepoint) or is_latin_lower(effective_codepoint):
        return chr(effective_codepoint)
    if is_symbol_codepoint(effective_codepoint):
        return chr(effective_codepoint)
    return None



def format_protocol_key_id(event: ProtocolEvent) -> str | None:
    key_name = key_name_from_codepoint(event.codepoint, event.base_layout_key)
    if key_name is None:
        return None
    return format_key_id(key_name, event.modifiers)



def parse_key_spec(key_id: str) -> KeySpec | None:
    parts = [part for part in key_id.lower().split("+") if part]
    if not parts:
        return None

    key_name = normalize_key_name(parts[-1])
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



def key_specs_equal(left: KeySpec, right: KeySpec) -> bool:
    return left.key == right.key and left.modifiers == right.modifiers



def raw_ctrl_char(key_name: str) -> str | None:
    lower_key_name = key_name.lower()
    codepoint = ord(lower_key_name)
    if is_latin_lower(codepoint) or lower_key_name in ("[", "\\", "]", "_"):
        return chr(codepoint & 0x1F)
    if lower_key_name == "-":
        return chr(31)
    return None
