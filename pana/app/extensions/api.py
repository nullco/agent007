"""Core types and classes for the Pana extension API.

Extension authors import from this module::

    from pana.app.extensions.api import ExtensionAPI, ExtensionContext, ToolDefinition, CommandDefinition
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from pana.app.context import UIContext

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    """Result of a shell command executed via :meth:`ExtensionAPI.exec`."""

    stdout: str
    stderr: str
    code: int
    killed: bool = False


@dataclass
class ToolExecutionResult:
    """Normalized result returned by extension and built-in tools."""

    content: str
    details: object | None = None
    is_error: bool = False


ToolReturnValue = str | ToolExecutionResult
ToolExecuteCallable = Callable[..., Coroutine[object, object, ToolReturnValue] | ToolReturnValue]
CommandHandler = Callable[..., Coroutine[object, object, None] | None]


@dataclass(frozen=True)
class SourceInfo:
    """Metadata describing where an extension was loaded from."""

    path: str
    name: str
    scope: Literal["global", "project", "cli", "unknown"]


@dataclass(frozen=True)
class ModelInfo:
    """Public model metadata exposed to extensions."""

    provider_name: str
    model_name: str
    thinking_level: str


@dataclass
class ToolDefinition:
    """Definition of a custom tool registered by an extension.

    The ``execute`` function's type annotations define the tool's parameter
    schema unless ``parameters_schema`` is provided explicitly.
    """

    name: str
    execute: ToolExecuteCallable
    description: str = ""
    label: str = ""
    parameters_schema: dict[str, object] | None = None
    prompt_snippet: str | None = None


@dataclass
class CommandDefinition:
    """Definition of a slash command registered by an extension.

    The ``handler`` is called with ``(args: str, ctx: ExtensionContext)``
    when the user runs the command.
    """

    description: str
    handler: CommandHandler


@dataclass
class ExtensionContext:
    """Context object passed to every extension handler.

    Attributes:
        cwd: Current working directory.
        ui: Full UI context.
        signal: Active cancellation event, or ``None`` outside a run.
        model: Public model metadata for the active agent, if any.
    """

    cwd: str
    ui: UIContext
    signal: asyncio.Event | None = None
    model: ModelInfo | None = None
    _is_idle: Callable[[], bool] | None = None
    _abort: Callable[[], None] | None = None
    _shutdown: Callable[[], None] | None = None
    _get_system_prompt: Callable[[], str] | None = None

    def is_idle(self) -> bool:
        """Return whether the app is currently idle."""
        if self._is_idle is None:
            return True
        return self._is_idle()

    def abort(self) -> None:
        """Abort the current run if one is active."""
        if self._abort is not None:
            self._abort()

    def shutdown(self) -> None:
        """Request a graceful shutdown."""
        if self._shutdown is not None:
            self._shutdown()

    def get_system_prompt(self) -> str:
        """Return the current effective system prompt."""
        if self._get_system_prompt is None:
            return ""
        return self._get_system_prompt()


@dataclass
class SessionStartEvent:
    """Fired once when the application session begins."""


@dataclass
class SessionShutdownEvent:
    """Fired when the application is about to exit."""


class InputContinueResult(TypedDict):
    action: Literal["continue"]


class InputTransformResult(TypedDict):
    action: Literal["transform"]
    text: str


class InputHandledResult(TypedDict):
    action: Literal["handled"]


InputEventResult = InputContinueResult | InputTransformResult | InputHandledResult


@dataclass
class InputEvent:
    """Fired when the user submits text, before command dispatch."""

    text: str
    source: str = "interactive"


class BeforeAgentStartEventResult(TypedDict, total=False):
    system_prompt: str


@dataclass
class BeforeAgentStartEvent:
    """Fired after input processing, before the agent loop starts.

    Handlers may return ``{"system_prompt": "extra text"}`` to append
    additional instructions to the system prompt for this turn only.
    """

    prompt: str
    system_prompt: str = ""


@dataclass
class AgentStartEvent:
    """Fired once per user prompt, just before the agent loop begins."""

    prompt: str


@dataclass
class AgentEndEvent:
    """Fired once per user prompt, after the agent loop completes."""

    prompt: str


@dataclass
class TurnStartEvent:
    """Fired at the start of each LLM request turn."""

    turn_index: int


@dataclass
class TurnEndEvent:
    """Fired after each round of tool execution completes."""

    turn_index: int


class ToolCallEventResult(TypedDict, total=False):
    block: bool
    reason: str


@dataclass
class ToolCallEvent:
    """Fired before a tool executes."""

    tool_name: str
    input: dict[str, object] = field(default_factory=dict)
    tool_call_id: str | None = None


class ToolResultEventResult(TypedDict, total=False):
    content: str
    details: object | None
    is_error: bool


@dataclass
class ToolResultEvent:
    """Fired after a tool completes, before the result is returned to the agent."""

    tool_name: str
    input: dict[str, object]
    content: str
    details: object | None = None
    is_error: bool = False
    tool_call_id: str | None = None


@dataclass
class ToolExecutionStartEvent:
    """Fired immediately before a tool begins executing."""

    tool_name: str
    args: dict[str, object]
    tool_call_id: str | None = None


@dataclass
class ToolExecutionEndEvent:
    """Fired immediately after a tool finishes executing."""

    tool_name: str
    args: dict[str, object]
    result: ToolExecutionResult
    tool_call_id: str | None = None


class ExtensionAPI:
    """API object passed to each extension's ``setup()`` function."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., object]]] = {}
        self._tools: list[ToolDefinition] = []
        self._commands: dict[str, CommandDefinition] = {}

    def on(self, event: str, handler: Callable[..., object] | None = None) -> Callable[..., object]:
        """Subscribe *handler* to *event*."""
        if handler is not None:
            self._handlers.setdefault(event, []).append(handler)
            return handler

        def decorator(fn: Callable[..., object]) -> Callable[..., object]:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return decorator

    def register_tool(self, definition: ToolDefinition) -> None:
        """Register a custom tool the LLM can call."""
        self._tools.append(definition)

    def register_command(self, name: str, definition: CommandDefinition) -> None:
        """Register a slash command."""
        self._commands[name] = definition

    def get_handlers(self, event: str) -> list[Callable[..., object]]:
        """Return handlers registered for *event*."""
        return list(self._handlers.get(event, []))

    def get_tools(self) -> list[ToolDefinition]:
        """Return tools registered by this extension."""
        return list(self._tools)

    def get_commands(self) -> dict[str, CommandDefinition]:
        """Return commands registered by this extension."""
        return dict(self._commands)

    async def exec(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        signal: asyncio.Event | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """Execute a shell command and return its output."""
        effective_cwd = cwd or str(Path.cwd())
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                command,
                *(args or []),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=effective_cwd,
            )

            comm_coro = proc.communicate()

            if signal is not None:
                cancel_task = asyncio.ensure_future(signal.wait())
                comm_task = asyncio.ensure_future(comm_coro)
                try:
                    done, _ = await asyncio.wait(
                        {cancel_task, comm_task},
                        timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    if not cancel_task.done():
                        cancel_task.cancel()

                if cancel_task in done:
                    comm_task.cancel()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return ExecResult(stdout="", stderr="Cancelled", code=-1, killed=True)

                if not comm_task.done():
                    comm_task.cancel()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return ExecResult(stdout="", stderr="Timed out", code=-1, killed=True)

                stdout_bytes, stderr_bytes = comm_task.result()
            else:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(comm_coro, timeout=timeout)

            return ExecResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                code=proc.returncode or 0,
            )

        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except OSError:
                    pass
            return ExecResult(stdout="", stderr="Timed out", code=-1, killed=True)
        except Exception as exc:
            return ExecResult(stdout="", stderr=str(exc), code=-1)


def normalize_tool_execution_result(value: ToolReturnValue | object) -> ToolExecutionResult:
    """Return a :class:`ToolExecutionResult` for any supported tool return value."""
    if isinstance(value, ToolExecutionResult):
        return value
    return ToolExecutionResult(content=str(value))
