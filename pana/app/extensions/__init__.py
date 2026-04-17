"""Pana extensions package.

Extensions are Python modules placed in:

* ``~/.pana/extensions/*.py``  (global)
* ``~/.pana/extensions/*/__init__.py``  (global, package style)
* ``.pana/extensions/*.py``  (project-local)
* ``.pana/extensions/*/__init__.py``  (project-local, package style)

or loaded explicitly with the ``-e`` / ``--extension`` CLI flag.

Each extension must export a ``setup(pana: ExtensionAPI)`` function::

    from pana.app.extensions import ExtensionAPI, ToolDefinition, CommandDefinition

    def setup(pana: ExtensionAPI) -> None:
        pana.on("session_start", lambda event, ctx: ctx.ui.notify("Loaded!"))
"""

from pana.app.extensions.api import (
    AgentEndEvent,
    AgentStartEvent,
    BeforeAgentStartEvent,
    CommandDefinition,
    ExecResult,
    ExtensionAPI,
    ExtensionContext,
    InputEvent,
    ModelInfo,
    SessionShutdownEvent,
    SessionStartEvent,
    SourceInfo,
    ToolCallEvent,
    ToolDefinition,
    ToolExecutionEndEvent,
    ToolExecutionResult,
    ToolExecutionStartEvent,
    ToolResultEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from pana.app.extensions.loader import build_source_info, discover_extension_paths, load_extension
from pana.app.extensions.manager import ExtensionManager

__all__ = [
    # API
    "ExtensionAPI",
    "ExtensionContext",
    # Definitions
    "ToolDefinition",
    "CommandDefinition",
    "ExecResult",
    "ToolExecutionResult",
    "SourceInfo",
    "ModelInfo",
    # Events
    "SessionStartEvent",
    "SessionShutdownEvent",
    "InputEvent",
    "BeforeAgentStartEvent",
    "AgentStartEvent",
    "AgentEndEvent",
    "TurnStartEvent",
    "TurnEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ToolExecutionStartEvent",
    "ToolExecutionEndEvent",
    # Infrastructure
    "ExtensionManager",
    "build_source_info",
    "discover_extension_paths",
    "load_extension",
]
