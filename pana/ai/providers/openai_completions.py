"""Reusable OpenAI Chat Completions API client and stream.

Any provider that speaks the OpenAI Chat Completions API (DeepSeek,
OpenCode Go, etc.) can instantiate ``OpenAICompletionsClient`` with a
configured ``AsyncOpenAI`` instance.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from pana.ai.types import (
    AssistantMessage,
    Message,
    ModelSettings,
    StreamDelta,
    TextDelta,
    ThinkingDelta,
    ToolCallArgsDelta,
    ToolCallDone,
    ToolCallStart,
    ToolDef,
    ToolResultMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


def build_messages(
    messages: list[Message],
    system_prompt: str | None = None,
) -> list[dict]:
    """Convert internal messages to Chat Completions format."""
    items: list[dict] = []
    if system_prompt:
        items.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if isinstance(msg, UserMessage):
            items.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AssistantMessage):
            assistant: dict = {
                "role": "assistant",
                "content": msg.content,
            }
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.thinking:
                # Normalise to reasoning_content for providers like OpenCode Go
                # that expect it on replay.
                assistant["reasoning_content"] = msg.thinking
            items.append(assistant)
        elif isinstance(msg, ToolResultMessage):
            items.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                }
            )
    return items


def build_tools(tool_defs: list[ToolDef]) -> list[dict]:
    """Convert ToolDef list to Chat Completions function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": td.parameters,
                "strict": False,
            },
        }
        for td in tool_defs
    ]


class OpenAICompletionsStream:
    """Wraps an OpenAI Chat Completions streaming response, yielding StreamDeltas."""

    def __init__(self, response) -> None:
        self._response = response
        self._closed = False
        self._tool_calls: dict[int, dict] = {}
        self._done_emitted: set[int] = set()

    async def __aiter__(self) -> AsyncIterator[StreamDelta]:
        try:
            async for chunk in self._response:
                if self._closed:
                    break
                for delta in self._map_chunk(chunk):
                    yield delta
        except Exception:
            if not self._closed:
                raise

    async def close(self) -> None:
        self._closed = True
        try:
            await self._response.close()
        except Exception:
            pass

    def _map_chunk(self, chunk) -> list[StreamDelta]:
        deltas: list[StreamDelta] = []
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            return deltas

        delta = choice.delta
        if delta is None:
            return deltas

        # Text content
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            deltas.append(TextDelta(content=content))

        # Reasoning / thinking — multiple field names are used by different
        # providers (e.g. DeepSeek uses ``reasoning_content``, others use
        # ``reasoning`` or ``reasoning_text``).
        reasoning_fields = ["reasoning_content", "reasoning", "reasoning_text"]
        for field in reasoning_fields:
            val = getattr(delta, field, None)
            if isinstance(val, str) and val:
                deltas.append(ThinkingDelta(content=val))
                break

        # Tool calls
        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                idx = tc.index
                existing = self._tool_calls.get(idx)
                if existing is None:
                    existing = {
                        "id": tc.id or "",
                        "name": tc.function.name if tc.function else "",
                        "arguments": "",
                    }
                    self._tool_calls[idx] = existing
                    if tc.id or (tc.function and tc.function.name):
                        deltas.append(
                            ToolCallStart(
                                tool_call_id=existing["id"],
                                tool_name=existing["name"],
                            )
                        )

                if tc.function and tc.function.arguments:
                    existing["arguments"] += tc.function.arguments
                    deltas.append(
                        ToolCallArgsDelta(
                            tool_call_id=existing["id"],
                            args_fragment=tc.function.arguments,
                        )
                    )

        # Finalise pending tool calls when the choice signals completion.
        if choice.finish_reason and self._tool_calls:
            for idx in sorted(self._tool_calls):
                if idx in self._done_emitted:
                    continue
                tc = self._tool_calls[idx]
                if tc["id"] and tc["name"]:
                    deltas.append(
                        ToolCallDone(
                            tool_call_id=tc["id"],
                            tool_name=tc["name"],
                            arguments=tc["arguments"],
                        )
                    )
                    self._done_emitted.add(idx)

        return deltas


class OpenAICompletionsClient:
    """ModelClient implementation for any OpenAI Chat Completions endpoint."""

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        *,
        thinking_mode: str = "reasoning_effort",
    ) -> None:
        self._client = openai_client
        self._thinking_mode = thinking_mode

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDef],
        system_prompt: str | None = None,
        settings: ModelSettings | None = None,
    ) -> OpenAICompletionsStream:
        items = build_messages(messages, system_prompt)
        tool_specs = build_tools(tools) if tools else []

        kwargs: dict = {
            "model": model,
            "messages": items,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tool_specs:
            kwargs["tools"] = tool_specs

        self._apply_thinking(kwargs, settings)

        response = await self._client.chat.completions.create(**kwargs)
        return OpenAICompletionsStream(response)

    def _apply_thinking(
        self,
        kwargs: dict,
        settings: ModelSettings | None,
    ) -> None:
        if not settings or not settings.thinking:
            return

        if self._thinking_mode == "reasoning_effort":
            kwargs["reasoning_effort"] = settings.thinking
        elif self._thinking_mode == "deepseek":
            kwargs["reasoning_effort"] = settings.thinking
        elif self._thinking_mode == "qwen":
            extra = kwargs.setdefault("extra_body", {})
            extra["enable_thinking"] = True
