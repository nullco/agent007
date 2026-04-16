"""Terminal protocol helpers and controllers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pana.tui.protocols.keyboard import KeyboardProtocolController, KeyboardProtocolMode

__all__ = ["KeyboardProtocolController", "KeyboardProtocolMode"]



def __getattr__(name: str) -> object:
    if name in {"KeyboardProtocolController", "KeyboardProtocolMode"}:
        from pana.tui.protocols.keyboard import (
            KeyboardProtocolController,
            KeyboardProtocolMode,
        )

        exports = {
            "KeyboardProtocolController": KeyboardProtocolController,
            "KeyboardProtocolMode": KeyboardProtocolMode,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
