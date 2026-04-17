"""Extension manager and event dispatch helpers."""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pana.app.context import UIContext
from pana.app.extensions.api import (
    BeforeAgentStartEvent,
    BeforeAgentStartEventResult,
    CommandDefinition,
    ExtensionAPI,
    ExtensionContext,
    InputEvent,
    InputEventResult,
    ModelInfo,
    SourceInfo,
    ToolCallEvent,
    ToolCallEventResult,
    ToolDefinition,
    ToolExecutionEndEvent,
    ToolExecutionResult,
    ToolExecutionStartEvent,
    ToolResultEvent,
    normalize_tool_execution_result,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedExtension:
    source: SourceInfo
    api: ExtensionAPI


class ExtensionManager:
    """Holds loaded extensions and dispatches their events."""

    def __init__(self, ui: UIContext) -> None:
        self._ui = ui
        self._extensions: list[LoadedExtension] = []

    def add_api(self, api: ExtensionAPI, source_info: SourceInfo | None = None) -> None:
        """Register a loaded extension API instance."""
        source = source_info or SourceInfo(
            path="<unknown>",
            name="unknown",
            scope="unknown",
        )
        self._extensions.append(LoadedExtension(source=source, api=api))

    @property
    def has_extensions(self) -> bool:
        """Return ``True`` if at least one extension has been loaded."""
        return bool(self._extensions)

    def make_context(self, signal: asyncio.Event | None = None) -> ExtensionContext:
        """Create an :class:`ExtensionContext` for callbacks."""
        return ExtensionContext(
            cwd=str(Path.cwd()),
            ui=self._ui,
            signal=signal,
            model=self._build_model_info(),
            _is_idle=self._ui.is_idle,
            _abort=self._ui.abort_current,
            _shutdown=self._ui.shutdown,
            _get_system_prompt=self._ui.get_current_system_prompt,
        )

    def _build_model_info(self) -> ModelInfo | None:
        agent = self._ui.agent
        if agent is None:
            return None
        return ModelInfo(
            provider_name=agent.provider_name,
            model_name=agent.model_name,
            thinking_level=agent.thinking_level,
        )

    def _iter_handlers(self, event: str):
        for extension in self._extensions:
            for handler in extension.api.get_handlers(event):
                yield extension, handler

    async def _call_handler(
        self,
        extension: LoadedExtension,
        event: str,
        handler: object,
        event_data: object,
        ctx: ExtensionContext,
    ) -> object | None:
        try:
            ret = handler(event_data, ctx)
            if asyncio.iscoroutine(ret):
                return await ret
            return ret
        except Exception:
            logger.exception(
                "Error in extension handler %r for event %r from %s",
                handler,
                event,
                extension.source.path,
            )
            return None

    async def emit_simple(self, event: str, event_data: object, ctx: ExtensionContext) -> None:
        """Emit a fire-and-forget event to every handler."""
        for extension, handler in self._iter_handlers(event):
            await self._call_handler(extension, event, handler, event_data, ctx)

    async def emit(self, event: str, event_data: object, ctx: ExtensionContext) -> None:
        """Backward-compatible alias for simple event emission."""
        await self.emit_simple(event, event_data, ctx)

    async def dispatch_input(
        self,
        event_data: InputEvent,
        ctx: ExtensionContext,
    ) -> InputEventResult:
        """Dispatch the input event with transform/handled semantics."""
        current_text = event_data.text
        for extension, handler in self._iter_handlers("input"):
            event = InputEvent(text=current_text, source=event_data.source)
            ret = await self._call_handler(extension, "input", handler, event, ctx)
            if not isinstance(ret, dict):
                continue
            action = ret.get("action", "continue")
            if action == "handled":
                return {"action": "handled"}
            if action == "transform" and isinstance(ret.get("text"), str):
                current_text = ret["text"]

        if current_text != event_data.text:
            return {"action": "transform", "text": current_text}
        return {"action": "continue"}

    async def dispatch_before_agent_start(
        self,
        event_data: BeforeAgentStartEvent,
        ctx: ExtensionContext,
    ) -> BeforeAgentStartEventResult | None:
        """Dispatch before-agent-start handlers in load order."""
        system_prompt = event_data.system_prompt
        changed = False
        for extension, handler in self._iter_handlers("before_agent_start"):
            event = BeforeAgentStartEvent(
                prompt=event_data.prompt,
                system_prompt=system_prompt,
            )
            ret = await self._call_handler(
                extension,
                "before_agent_start",
                handler,
                event,
                ctx,
            )
            if isinstance(ret, dict) and isinstance(ret.get("system_prompt"), str):
                system_prompt = ret["system_prompt"]
                changed = True

        if not changed:
            return None
        return {"system_prompt": system_prompt}

    async def dispatch_tool_call(
        self,
        tool_name: str,
        input_data: dict[str, object],
        ctx: ExtensionContext,
        *,
        tool_call_id: str | None = None,
    ) -> ToolCallEventResult | None:
        """Dispatch the tool-call event and stop on the first block."""
        event = ToolCallEvent(
            tool_name=tool_name,
            input=input_data,
            tool_call_id=tool_call_id,
        )
        for extension, handler in self._iter_handlers("tool_call"):
            ret = await self._call_handler(extension, "tool_call", handler, event, ctx)
            if isinstance(ret, dict) and ret.get("block"):
                reason = ret.get("reason")
                if isinstance(reason, str):
                    return {"block": True, "reason": reason}
                return {"block": True}
        return None

    async def dispatch_tool_result(
        self,
        tool_name: str,
        input_data: dict[str, object],
        result: ToolExecutionResult,
        ctx: ExtensionContext,
        *,
        tool_call_id: str | None = None,
    ) -> ToolExecutionResult:
        """Dispatch tool-result middleware and return the final result."""
        current = ToolExecutionResult(
            content=result.content,
            details=result.details,
            is_error=result.is_error,
        )
        for extension, handler in self._iter_handlers("tool_result"):
            event = ToolResultEvent(
                tool_name=tool_name,
                input=input_data,
                content=current.content,
                details=current.details,
                is_error=current.is_error,
                tool_call_id=tool_call_id,
            )
            ret = await self._call_handler(extension, "tool_result", handler, event, ctx)
            if not isinstance(ret, dict):
                continue
            if "content" in ret:
                current.content = str(ret["content"])
            if "details" in ret:
                current.details = ret["details"]
            if "is_error" in ret:
                current.is_error = bool(ret["is_error"])
        return current

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Return all registered tool definitions in load order."""
        tools: list[ToolDefinition] = []
        for extension in self._extensions:
            tools.extend(extension.api.get_tools())
        return tools

    def build_extension_tool(
        self,
        definition: ToolDefinition,
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> Callable[..., object]:
        """Convert a tool definition into an agent-compatible async function."""
        execute_fn = definition.execute
        manager_ref = self

        @functools.wraps(execute_fn)
        async def wrapper(**kwargs: object) -> str:
            ctx = manager_ref.make_context(signal=cancel_event_getter())
            call_args = dict(kwargs)

            blocked = await manager_ref.dispatch_tool_call(definition.name, call_args, ctx)
            if isinstance(blocked, dict) and blocked.get("block"):
                reason = blocked.get("reason") or "Blocked by extension"
                return f"Error: {reason}"

            await manager_ref.emit_simple(
                "tool_execution_start",
                ToolExecutionStartEvent(tool_name=definition.name, args=dict(call_args)),
                ctx,
            )

            try:
                raw_result = execute_fn(**call_args)
                if asyncio.iscoroutine(raw_result):
                    raw_result = await raw_result
                result = normalize_tool_execution_result(raw_result)
            except Exception as exc:
                result = ToolExecutionResult(
                    content=f"Error: {exc}",
                    is_error=True,
                )

            result = await manager_ref.dispatch_tool_result(
                definition.name,
                call_args,
                result,
                ctx,
            )
            await manager_ref.emit_simple(
                "tool_execution_end",
                ToolExecutionEndEvent(
                    tool_name=definition.name,
                    args=dict(call_args),
                    result=result,
                ),
                ctx,
            )
            return result.content

        wrapper.__name__ = definition.name
        wrapper.__doc__ = definition.description or execute_fn.__doc__ or ""
        if definition.parameters_schema is not None:
            setattr(wrapper, "__pana_tool_parameters_schema__", definition.parameters_schema)
        return wrapper

    def wrap_builtin_tool(
        self,
        original_fn: Callable[..., object],
        tool_name: str,
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> Callable[..., object]:
        """Wrap a built-in tool function with extension lifecycle hooks."""
        manager_ref = self

        @functools.wraps(original_fn)
        async def wrapper(**kwargs: object) -> str:
            ctx = manager_ref.make_context(signal=cancel_event_getter())
            call_args = dict(kwargs)

            blocked = await manager_ref.dispatch_tool_call(tool_name, call_args, ctx)
            if isinstance(blocked, dict) and blocked.get("block"):
                reason = blocked.get("reason") or "Blocked by extension"
                return f"Error: {reason}"

            await manager_ref.emit_simple(
                "tool_execution_start",
                ToolExecutionStartEvent(tool_name=tool_name, args=dict(call_args)),
                ctx,
            )

            try:
                raw_result = original_fn(**call_args)
                if asyncio.iscoroutine(raw_result):
                    raw_result = await raw_result
                result = normalize_tool_execution_result(raw_result)
            except Exception as exc:
                result = ToolExecutionResult(
                    content=f"Error: {exc}",
                    is_error=True,
                )

            result = await manager_ref.dispatch_tool_result(
                tool_name,
                call_args,
                result,
                ctx,
            )
            await manager_ref.emit_simple(
                "tool_execution_end",
                ToolExecutionEndEvent(
                    tool_name=tool_name,
                    args=dict(call_args),
                    result=result,
                ),
                ctx,
            )
            return result.content

        return wrapper

    def build_all_tools(
        self,
        builtin_fns: list[Callable[..., object]],
        builtin_names: list[str],
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> list[Callable[..., object]]:
        """Return wrapped built-ins followed by extension tools."""
        tools: list[Callable[..., object]] = []
        for fn, name in zip(builtin_fns, builtin_names):
            tools.append(self.wrap_builtin_tool(fn, name, cancel_event_getter))
        for definition in self.get_tool_definitions():
            tools.append(self.build_extension_tool(definition, cancel_event_getter))
        return tools

    def build_command_objects(self, existing_names: set[str] | None = None) -> list[object]:
        """Build command objects for every extension command definition."""
        used_names = set(existing_names or set())
        objects: list[object] = []
        for extension in self._extensions:
            for command_name, definition in extension.api.get_commands().items():
                invocation_name = command_name
                if invocation_name in used_names:
                    suffix = 2
                    while f"{command_name}:{suffix}" in used_names:
                        suffix += 1
                    invocation_name = f"{command_name}:{suffix}"
                    logger.warning(
                        "Renaming extension command /%s from %s to /%s due to a name conflict",
                        command_name,
                        extension.source.path,
                        invocation_name,
                    )
                used_names.add(invocation_name)
                objects.append(_make_ext_command(invocation_name, definition, self))
        return objects


def _make_ext_command(cmd_name: str, definition: CommandDefinition, manager: ExtensionManager) -> object:
    from pana.app.commands.base import Command

    handler = definition.handler

    class _ExtCommand(Command):
        name = cmd_name
        description = definition.description

        async def execute(self, ctx: UIContext, args: str) -> None:
            ext_ctx = manager.make_context()
            ret = handler(args, ext_ctx)
            if asyncio.iscoroutine(ret):
                await ret

    return _ExtCommand()
