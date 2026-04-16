"""xterm modifyOtherKeys parsing."""

from __future__ import annotations

import re

from pana.tui.keys.common import Modifier, ModifyOtherKeysDict, ProtocolEvent

_MODIFY_OTHER_RE = re.compile(r"^\x1b\[27;(\d+);(\d+)~$")



def parse_xterm_modify_other_keys_event(data: str) -> ProtocolEvent | None:
    match = _MODIFY_OTHER_RE.match(data)
    if not match:
        return None
    return ProtocolEvent(
        codepoint=int(match.group(2)),
        modifiers=Modifier(max(int(match.group(1)) - 1, 0)),
        event_type="press",
    )



def parse_xterm_modify_other_keys(data: str) -> ModifyOtherKeysDict | None:
    event = parse_xterm_modify_other_keys_event(data)
    if event is None:
        return None
    return {"codepoint": event.codepoint, "modifier": int(event.modifiers)}


__all__ = ["parse_xterm_modify_other_keys", "parse_xterm_modify_other_keys_event"]
