"""Provider-agnostic types for the AI abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class UserMessage:
    content: str


@dataclass
class AssistantMessage:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: str | None = None


@dataclass
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict


@dataclass
class ModelSettings:
    thinking: str | None = None


@dataclass
class TextDelta:
    content: str


@dataclass
class ThinkingDelta:
    content: str


@dataclass
class ToolCallStart:
    tool_call_id: str
    tool_name: str


@dataclass
class ToolCallArgsDelta:
    tool_call_id: str
    args_fragment: str


@dataclass
class ToolCallDone:
    tool_call_id: str
    tool_name: str
    arguments: str


StreamDelta = TextDelta | ThinkingDelta | ToolCallStart | ToolCallArgsDelta | ToolCallDone
