"""User chat bubble with OSC 133 semantic zone markers."""
from __future__ import annotations

from pana.tui.components.text import Text
from pana.tui.terminal_modes import TerminalModes


class UserMessage(Text):
    """User chat bubble with OSC 133 semantic zone markers."""

    def render(self, width: int) -> list[str]:
        lines = super().render(width)
        if not lines:
            return lines
        lines = list(lines)
        lines[0] = TerminalModes.OSC133_ZONE_START + lines[0]
        lines[-1] = lines[-1] + TerminalModes.OSC133_ZONE_END + TerminalModes.OSC133_ZONE_FINAL
        return lines
