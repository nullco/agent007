"""Reusable OpenAI Responses API client and stream.

Any provider that speaks the OpenAI Responses API (GitHub Copilot, OpenAI
direct, Azure OpenAI, etc.) can instantiate ``OpenAIResponsesClient`` with
a configured ``AsyncOpenAI`` instance.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
    ResponseTextDeltaEvent,
)

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

def build_input(messages: list[Message]) -> list[dict]:
    """Convert internal messages to OpenAI Responses API input format."""
    items: list[dict] = []
    for msg in messages:
        if isinstance(msg, UserMessage):
            items.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AssistantMessage):
            if msg.content:
                items.append({"role": "assistant", "content": msg.content})
            for tc in msg.tool_calls:
                items.append({
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                })
        elif isinstance(msg, ToolResultMessage):
            items.append({
                "type": "function_call_output",
                "call_id": msg.tool_call_id,
                "output": msg.content,
            })
    return items


def build_tools(tool_defs: list[ToolDef]) -> list[dict]:
    """Convert ToolDef list to OpenAI Responses API tool format."""
    tools = []
    for td in tool_defs:
        tools.append({
            "type": "function",
            "name": td.name,
            "description": td.description,
            "parameters": td.parameters,
        })
    return tools


class OpenAIResponsesStream:
    """Wraps an OpenAI Responses API streaming response, yielding StreamDeltas."""

    def __init__(self, response) -> None:
        self._response = response
        self._closed = False
        self._call_ids: dict[int, str] = {}
        self._names: dict[int, str] = {}

    async def __aiter__(self) -> AsyncIterator[StreamDelta]:
        try:
            async for event in self._response:
                if self._closed:
                    break

                delta = self._map_event(event)
                if delta is not None:
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

    def _map_event(self, event) -> StreamDelta | None:
        if isinstance(event, ResponseTextDeltaEvent):
            return TextDelta(content=event.delta)

        if isinstance(event, ResponseOutputItemAddedEvent):
            item = event.item
            if hasattr(item, "call_id") and item.call_id:
                self._call_ids[event.output_index] = item.call_id
                self._names[event.output_index] = item.name
                return ToolCallStart(
                    tool_call_id=item.call_id,
                    tool_name=item.name,
                )
            return None

        if isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            call_id = self._call_ids.get(event.output_index, event.item_id)
            return ToolCallArgsDelta(
                tool_call_id=call_id,
                args_fragment=event.delta,
            )

        if isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            call_id = self._call_ids.get(event.output_index, event.item_id)
            return ToolCallDone(
                tool_call_id=call_id,
                tool_name=event.name,
                arguments=event.arguments,
            )

        if hasattr(event, "type") and "reasoning" in getattr(event, "type", ""):
            if hasattr(event, "delta") and event.delta:
                return ThinkingDelta(content=event.delta)

        return None


class OpenAIResponsesClient:
    """ModelClient implementation for any OpenAI Responses API endpoint."""

    def __init__(self, openai_client: AsyncOpenAI) -> None:
        self._client = openai_client

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDef],
        system_prompt: str | None = None,
        settings: ModelSettings | None = None,
    ) -> OpenAIResponsesStream:
        input_items = build_input(messages)
        tool_specs = build_tools(tools) if tools else []

        kwargs: dict = {
            "model": model,
            "input": input_items,
            "stream": True,
        }

        if system_prompt:
            kwargs["instructions"] = system_prompt

        if tool_specs:
            kwargs["tools"] = tool_specs

        self._apply_thinking(kwargs, settings)

        response = await self._client.responses.create(**kwargs)
        return OpenAIResponsesStream(response)

    def _apply_thinking(
        self, kwargs: dict, settings: ModelSettings | None
    ) -> None:
        if settings and settings.thinking:
            kwargs["reasoning"] = {
                "effort": settings.thinking,
                "summary": "auto",
            }
