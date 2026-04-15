"""Kitty protocol escape sequences and parsers."""
from __future__ import annotations

import re

KITTY_KEYBOARD_QUERY = "\x1b[?u"
KITTY_KEYBOARD_ENABLE = "\x1b[>7u"
KITTY_KEYBOARD_DISABLE = "\x1b[<u"
KITTY_KEYBOARD_QUERY_RESPONSE_RE = re.compile(r"^\x1b\[\?(\d+)u$")

MODIFY_OTHER_KEYS_ON = "\x1b[>4;2m"
MODIFY_OTHER_KEYS_OFF = "\x1b[>4;0m"

KITTY_GRAPHICS_PREFIX = "\x1b_G"
KITTY_GRAPHICS_SUFFIX = "\x1b\\"


def parse_kitty_keyboard_query_response(data: str) -> int | None:
    """Return Kitty keyboard query flags when *data* is a query response."""
    match = KITTY_KEYBOARD_QUERY_RESPONSE_RE.match(data)
    if match is None:
        return None
    return int(match.group(1))
