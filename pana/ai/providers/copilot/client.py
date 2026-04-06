"""OpenAI Responses API client for GitHub Copilot."""

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

_THINKING_BUDGET = {
    "minimal": 128,
    "low": 1024,
    "medium": 4096,
    "high": 10240,
    "xhigh": 32768,
}


def _build_input(messages: list[Message]) -> list[dict]:
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


def _build_tools(tool_defs: list[ToolDef]) -> list[dict]:
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
    """Wraps an OpenAI Responses API streaming response, yielding StreamDeltas.

    Handles the Copilot item_id mismatch bug: Copilot emits different item_ids
    on each FunctionCallArgumentsDeltaEvent instead of reusing the original
    item.id from ResponseOutputItemAddedEvent. We track output_index → id
    to emit consistent tool_call_ids.
    """

    def __init__(self, response) -> None:
        self._response = response
        self._closed = False
        self._output_index_to_id: dict[int, str] = {}
        self._output_index_to_name: dict[int, str] = {}

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
                call_id = item.call_id
                self._output_index_to_id[event.output_index] = call_id
                self._output_index_to_name[event.output_index] = item.name
                return ToolCallStart(
                    tool_call_id=call_id,
                    tool_name=item.name,
                )
            return None

        if isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            tool_call_id = self._output_index_to_id.get(
                event.output_index, event.item_id
            )
            return ToolCallArgsDelta(
                tool_call_id=tool_call_id,
                args_fragment=event.delta,
            )

        if isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            tool_call_id = self._output_index_to_id.get(
                event.output_index, event.item_id
            )
            tool_name = self._output_index_to_name.get(event.output_index, "")
            return ToolCallDone(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=event.arguments,
            )

        if hasattr(event, "type") and "reasoning" in getattr(event, "type", ""):
            if hasattr(event, "delta") and event.delta:
                return ThinkingDelta(content=event.delta)

        return None


class CopilotClient:
    """ModelClient implementation using OpenAI SDK with Copilot proxy."""

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
        input_items = _build_input(messages)
        tool_specs = _build_tools(tools) if tools else []

        kwargs: dict = {
            "model": model,
            "input": input_items,
            "stream": True,
        }

        if system_prompt:
            kwargs["instructions"] = system_prompt

        if tool_specs:
            kwargs["tools"] = tool_specs

        if settings and settings.thinking and settings.thinking != "off":
            budget = _THINKING_BUDGET.get(settings.thinking, 4096)
            kwargs["reasoning"] = {
                "effort": "high" if budget >= 10240 else "medium",
                "summary": "auto",
            }

        response = await self._client.responses.create(**kwargs)
        return OpenAIResponsesStream(response)
