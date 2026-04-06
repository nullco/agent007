import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pana.agents.skills import Skill, discover_skills
from pana.agents.system_prompt import build_system_prompt
from pana.agents.tool_streams import (
    ToolStreamHandler,
    build_stream_handlers,
    try_extract_partial_args,
)
from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write
from pana.ai.client import ModelStream
from pana.ai.tools import function_to_tool_def
from pana.ai.types import (
    AssistantMessage,
    ModelSettings,
    StreamDelta,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolCallArgsDelta,
    ToolCallDone,
    ToolCallStart,
    ToolDef,
    ToolResultMessage,
    UserMessage,
)

if TYPE_CHECKING:
    from pana.ai.providers.model import Model
    from pana.app.extensions.manager import ExtensionManager

logger = logging.getLogger(__name__)


THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")

_BUILTIN_TOOL_FNS = [tool_read, tool_edit, tool_write, tool_bash]
_BUILTIN_TOOL_NAMES = ["read", "edit", "write", "bash"]


@dataclass
class ToolCallEvent:
    """Fired as soon as the model commits to invoking a tool (args may be partial)."""

    tool_call_id: str | None
    tool_name: str
    args: dict | str | None


@dataclass
class ToolCallUpdateEvent:
    """Fired after a tool's arguments are fully received, to update an earlier ToolCallEvent."""

    tool_call_id: str | None
    tool_name: str
    args: dict | str | None


@dataclass
class ToolResultEvent:
    """Fired when a tool returns its result."""

    tool_call_id: str | None
    tool_name: str
    result: str
    elapsed_s: float | None = None
    is_error: bool = False


@dataclass
class TextEvent:
    """Fired for text content (streamed delta or final)."""

    text: str
    is_complete: bool = False


@dataclass
class ThinkingEvent:
    """Fired for thinking/reasoning content from the model."""

    text: str


StreamEvent = ToolCallEvent | ToolCallUpdateEvent | ToolResultEvent | TextEvent | ThinkingEvent


@dataclass
class _RunState:
    """Holds all mutable bookkeeping for a single agent run."""

    call_started: dict[str, float] = field(default_factory=dict)
    emitted_early_ids: set[str] = field(default_factory=set)
    stream_handlers: dict[str, ToolStreamHandler] = field(default_factory=build_stream_handlers)
    accumulated_text: str = ""
    accumulated_thinking: str = ""
    accumulated_args: dict[str, str] = field(default_factory=dict)


class Agent:

    def __init__(
        self,
        model: "Model",
        thinking_level: str = "medium",
        extension_manager: "ExtensionManager | None" = None,
        skills: list[Skill] | None = None,
    ) -> None:
        self._model = model
        self._thinking_level = thinking_level
        self._extension_manager = extension_manager
        self._skills = skills if skills is not None else discover_skills()
        self._extra_system_prompt: str | None = None
        self._current_cancel_event: asyncio.Event | None = None
        self._message_history: list = []
        self._tool_fns: dict[str, Callable] = {}
        self._tool_defs: list[ToolDef] = []
        self._rebuild_tools()

    def _get_extension_tool_snippets(self) -> dict[str, str]:
        if self._extension_manager is None:
            return {}
        return {
            defn.name: defn.description
            for defn in self._extension_manager.get_tool_definitions()
        }

    def _get_all_tools(self) -> list[Callable]:
        if self._extension_manager is None:
            return list(_BUILTIN_TOOL_FNS)

        def cancel_getter() -> asyncio.Event | None:
            return self._current_cancel_event

        return self._extension_manager.build_all_tools(
            _BUILTIN_TOOL_FNS, _BUILTIN_TOOL_NAMES, cancel_getter
        )

    def _rebuild_tools(self) -> None:
        all_tools = self._get_all_tools()
        self._tool_fns = {}
        self._tool_defs = []
        for fn in all_tools:
            td = function_to_tool_def(fn)
            self._tool_defs.append(td)
            self._tool_fns[td.name] = fn

    def _build_system_prompt(self) -> str:
        base_prompt = build_system_prompt(
            extra_tool_snippets=self._get_extension_tool_snippets(),
            skills=self._skills,
        )
        if self._extra_system_prompt:
            return f"{base_prompt}\n\n{self._extra_system_prompt.strip()}"
        return base_prompt

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def provider_name(self) -> str:
        return self._model.provider.name

    @property
    def thinking_level(self) -> str:
        return self._thinking_level

    def set_thinking_level(self, level: str) -> None:
        if level not in THINKING_LEVELS:
            raise ValueError(f"Invalid thinking level: {level!r}. Must be one of {THINKING_LEVELS}")
        self._thinking_level = level

    def set_extra_system_prompt(self, extra: str | None) -> None:
        if extra != self._extra_system_prompt:
            self._extra_system_prompt = extra

    def set_model(self, model: "Model") -> None:
        self._model = model

    def clear_history(self) -> None:
        self._message_history = []
        self._extra_system_prompt = None

    async def stream(
        self,
        user_input: str,
        event_handler: Callable[[StreamEvent], None],
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        await self._ensure_auth()
        self._current_cancel_event = cancel_event
        self._rebuild_tools()

        ext = self._extension_manager
        ext_ctx = ext.make_context(signal=cancel_event) if ext else None

        try:
            if ext and ext_ctx:
                from pana.app.extensions.api import AgentStartEvent

                await ext.emit("agent_start", AgentStartEvent(prompt=user_input), ext_ctx)

            self._message_history.append(UserMessage(content=user_input))
            turn_index = 0

            while True:
                if cancel_event and cancel_event.is_set():
                    break

                if ext and ext_ctx:
                    from pana.app.extensions.api import TurnStartEvent

                    await ext.emit("turn_start", TurnStartEvent(turn_index=turn_index), ext_ctx)

                state = _RunState()
                settings = ModelSettings(thinking=self._thinking_level)

                model_stream = await self._model.client.stream(
                    model=self._model.name,
                    messages=self._message_history,
                    tools=self._tool_defs,
                    system_prompt=self._build_system_prompt(),
                    settings=settings,
                )

                tool_calls = await self._consume_stream(
                    model_stream, state, event_handler, cancel_event
                )

                if cancel_event and cancel_event.is_set():
                    break

                assistant_msg = AssistantMessage(
                    content=state.accumulated_text or None,
                    tool_calls=tool_calls,
                    thinking=state.accumulated_thinking or None,
                )
                self._message_history.append(assistant_msg)

                if not tool_calls:
                    if ext and ext_ctx:
                        from pana.app.extensions.api import TurnEndEvent

                        await ext.emit("turn_end", TurnEndEvent(turn_index=turn_index), ext_ctx)
                    break

                tool_results = await self._execute_tools(
                    tool_calls, state, event_handler, cancel_event
                )
                self._message_history.extend(tool_results)

                if ext and ext_ctx:
                    from pana.app.extensions.api import TurnEndEvent

                    await ext.emit("turn_end", TurnEndEvent(turn_index=turn_index), ext_ctx)

                turn_index += 1
                await asyncio.sleep(0)

            if ext and ext_ctx:
                from pana.app.extensions.api import AgentEndEvent

                await ext.emit("agent_end", AgentEndEvent(prompt=user_input), ext_ctx)
        finally:
            self._current_cancel_event = None

    async def _ensure_auth(self) -> None:
        if self._model.provider.should_reauthenticate():
            await self._model.provider.reauthenticate()
            model = await self._model.provider.build_model(self._model.name)
            self.set_model(model)

    async def _consume_stream(
        self,
        model_stream: ModelStream,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
        cancel_event: asyncio.Event | None,
    ) -> list[ToolCall]:
        tool_calls: list[ToolCall] = []
        tool_call_names: dict[str, str] = {}

        try:
            async for delta in model_stream:
                if cancel_event and cancel_event.is_set():
                    await model_stream.close()
                    break

                self._process_delta(delta, state, event_handler, tool_call_names)
        except Exception:
            if cancel_event and cancel_event.is_set():
                pass
            else:
                raise

        for tid, args_json in state.accumulated_args.items():
            name = tool_call_names.get(tid, "")
            tool_calls.append(ToolCall(id=tid, name=name, arguments=args_json))

        return tool_calls

    def _process_delta(
        self,
        delta: StreamDelta,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
        tool_call_names: dict[str, str],
    ) -> None:
        if isinstance(delta, TextDelta):
            state.accumulated_text += delta.content
            event_handler(TextEvent(text=state.accumulated_text))

        elif isinstance(delta, ThinkingDelta):
            state.accumulated_thinking += delta.content
            event_handler(ThinkingEvent(text=state.accumulated_thinking))

        elif isinstance(delta, ToolCallStart):
            tool_call_names[delta.tool_call_id] = delta.tool_name
            state.emitted_early_ids.add(delta.tool_call_id)
            state.call_started[delta.tool_call_id] = time.monotonic()
            state.accumulated_args[delta.tool_call_id] = ""
            event_handler(
                ToolCallEvent(
                    tool_call_id=delta.tool_call_id,
                    tool_name=delta.tool_name,
                    args=None,
                )
            )

        elif isinstance(delta, ToolCallArgsDelta):
            state.accumulated_args[delta.tool_call_id] = (
                state.accumulated_args.get(delta.tool_call_id, "") + delta.args_fragment
            )
            tool_name = tool_call_names.get(delta.tool_call_id, "")
            if tool_name in state.stream_handlers:
                raw = state.accumulated_args[delta.tool_call_id]
                partial = try_extract_partial_args(raw)
                if partial and "path" in partial:
                    handler = state.stream_handlers[tool_name]
                    if handler.should_emit_update(delta.tool_call_id, partial):
                        event_handler(
                            ToolCallUpdateEvent(
                                tool_call_id=delta.tool_call_id,
                                tool_name=tool_name,
                                args=partial,
                            )
                        )

        elif isinstance(delta, ToolCallDone):
            state.accumulated_args[delta.tool_call_id] = delta.arguments
            tool_name = tool_call_names.get(delta.tool_call_id, delta.tool_name)
            try:
                full_args = json.loads(delta.arguments)
            except (json.JSONDecodeError, ValueError):
                full_args = delta.arguments
            event_handler(
                ToolCallUpdateEvent(
                    tool_call_id=delta.tool_call_id,
                    tool_name=tool_name,
                    args=full_args,
                )
            )

    async def _execute_tools(
        self,
        tool_calls: list[ToolCall],
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
        cancel_event: asyncio.Event | None,
    ) -> list[ToolResultMessage]:
        results: list[ToolResultMessage] = []

        for tc in tool_calls:
            if cancel_event and cancel_event.is_set():
                break

            fn = self._tool_fns.get(tc.name)
            if fn is None:
                result_text = f"Error: unknown tool '{tc.name}'"
                is_error = True
            else:
                try:
                    kwargs = json.loads(tc.arguments) if tc.arguments else {}
                except (json.JSONDecodeError, ValueError):
                    kwargs = {}

                try:
                    if asyncio.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn):
                        result_text = await fn(**kwargs)
                    else:
                        result_text = fn(**kwargs)
                    is_error = result_text.lstrip().startswith("Error")
                except Exception as exc:
                    result_text = f"Error: {exc}"
                    is_error = True

            elapsed_s = None
            if tc.id in state.call_started:
                elapsed_s = time.monotonic() - state.call_started.pop(tc.id)

            event_handler(
                ToolResultEvent(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    result=result_text,
                    elapsed_s=elapsed_s,
                    is_error=is_error,
                )
            )

            results.append(
                ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=result_text,
                    is_error=is_error,
                )
            )

        return results
