"""ModelClient protocol — the abstraction each provider implements."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from pana.ai.types import Message, ModelSettings, StreamDelta, ToolDef


class ModelStream(Protocol):
    """Async iterator of stream deltas with cooperative cancellation."""

    def __aiter__(self) -> AsyncIterator[StreamDelta]: ...

    async def close(self) -> None: ...


class ModelClient(Protocol):
    """Provider-agnostic interface for streaming LLM responses."""

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDef],
        system_prompt: str | None = None,
        settings: ModelSettings | None = None,
    ) -> ModelStream: ...
