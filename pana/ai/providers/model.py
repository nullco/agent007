from __future__ import annotations

from dataclasses import dataclass, field

from pana.ai.client import ModelClient


@dataclass
class ModelInfo:
    display_name: str
    thinking_levels: list[str] = field(default_factory=list)
    default_thinking: str = "off"
    display_details: str = ""
    thinking_mode: str = "reasoning_effort"


class Model:
    def __init__(
        self,
        name: str,
        client: ModelClient,
        provider,
        info: ModelInfo | None = None,
    ):
        self.name = name
        self.client = client
        self.provider = provider
        self.info = info or ModelInfo(display_name=name)

    @property
    def display_name(self) -> str:
        return self.info.display_name

    @property
    def default_thinking(self) -> str:
        return self.info.default_thinking

    def resolve_thinking(self, level: str) -> str | None:
        """Return the thinking level to send to the provider.

        Returns ``None`` when the level is ``"off"`` or unsupported.
        """
        if level == "off":
            return None
        if level in self.info.thinking_levels:
            return level
        return None

    @property
    def supported_thinking_levels(self) -> list[str]:
        return ["off", *self.info.thinking_levels]
