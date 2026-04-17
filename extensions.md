# Pana extensions

This document explains everything you need to know to build an extension for Pana.

## Overview

A Pana extension is a Python module that exports a single function:

```python
def setup(pana: ExtensionAPI) -> None:
    ...
```

Inside `setup()`, you can:

- subscribe to lifecycle events with `pana.on(...)`
- register custom LLM-callable tools with `pana.register_tool(...)`
- register slash commands with `pana.register_command(...)`
- run shell commands with `await pana.exec(...)`
- interact with the UI through `ctx.ui`

Extensions are loaded into the main application process. They have the same permissions as the user running Pana.

---

## Extension locations

Pana auto-discovers extensions from these locations:

- `~/.pana/extensions/*.py`
- `~/.pana/extensions/*/__init__.py`
- `.pana/extensions/*.py`
- `.pana/extensions/*/__init__.py`

You can also load extensions explicitly with the CLI flag:

```bash
pana -e ./path/to/my_extension.py
pana -e ./path/to/my_extension_dir
```

If you pass a directory, Pana expects a Python package with `__init__.py` inside it.

### Discovery order

Extensions are loaded in this order:

1. global extensions in `~/.pana/extensions`
2. project-local extensions in `.pana/extensions`
3. explicit `-e/--extension` paths

Within a directory, files and subdirectories are loaded in sorted order.

That matters because event handlers run in extension load order.

---

## Minimal extension

```python
from pana.app.extensions.api import ExtensionAPI


def setup(pana: ExtensionAPI) -> None:
    @pana.on("session_start")
    async def on_start(event, ctx):
        ctx.ui.notify("Extension loaded!", "info")
```

Save it as:

- `~/.pana/extensions/my_extension.py`, or
- `.pana/extensions/my_extension.py`

Then run:

```bash
pana
```

---

## Recommended imports

Most extensions will import from:

```python
from pana.app.extensions.api import (
    CommandDefinition,
    ExtensionAPI,
    ToolDefinition,
    ToolExecutionResult,
)
```

If you want a shorter import path, this also works:

```python
from pana.app.extensions import (
    CommandDefinition,
    ExtensionAPI,
    ToolDefinition,
    ToolExecutionResult,
)
```

---

## The `setup()` function

Pana loads an extension module and looks for a callable named `setup`.

```python
def setup(pana: ExtensionAPI) -> None:
    ...
```

Inside `setup()`, you typically:

- register handlers with `@pana.on(...)`
- register tools with `pana.register_tool(...)`
- register commands with `pana.register_command(...)`

If `setup()` is missing, the extension is not loaded.

---

## ExtensionAPI

`ExtensionAPI` is the main entrypoint given to your extension.

### `pana.on(event_name)`

Registers an event handler.

```python
@pana.on("tool_call")
def guard(event, ctx):
    ...
```

You can also call it directly:

```python
pana.on("session_start", my_handler)
```

### `pana.register_tool(definition)`

Registers a custom tool the LLM can call.

### `pana.register_command(name, definition)`

Registers a slash command.

### `await pana.exec(command, args=None, *, signal=None, timeout=None, cwd=None)`

Runs a shell command.

It returns an `ExecResult`:

```python
@dataclass
class ExecResult:
    stdout: str
    stderr: str
    code: int
    killed: bool = False
```

Example:

```python
result = await pana.exec("git", ["status"], timeout=5)
if result.code == 0:
    print(result.stdout)
```

---

## ExtensionContext

Each event handler and command handler receives `ctx: ExtensionContext`.

```python
@dataclass
class ExtensionContext:
    cwd: str
    ui: UIContext
    signal: asyncio.Event | None
    model: ModelInfo | None
```

### `ctx.cwd`

Current working directory.

### `ctx.signal`

The cancellation event for the active run, or `None` when no run is active.

This is most useful in tool-related handlers.

### `ctx.model`

Public information about the active model, if one is selected.

```python
@dataclass(frozen=True)
class ModelInfo:
    provider_name: str
    model_name: str
    thinking_level: str
```

### `ctx.is_idle()`

Returns whether the app is currently idle.

### `ctx.abort()`

Aborts the current run if one is active.

### `ctx.shutdown()`

Requests a graceful shutdown.

### `ctx.get_system_prompt()`

Returns the current effective system prompt.

---

## UI methods: `ctx.ui`

Extensions can interact with the TUI through `ctx.ui`.

### Dialogs

#### `await ctx.ui.select(title, options, timeout=None)`

Shows a selector and returns the chosen option or `None`.

```python
choice = await ctx.ui.select("Choose a mode", ["fast", "safe"])
```

#### `await ctx.ui.confirm(title, message, timeout=None)`

Shows a confirmation prompt and returns `True` or `False`.

```python
ok = await ctx.ui.confirm("Dangerous command", "Allow it?")
```

#### `await ctx.ui.input(title, placeholder="", timeout=None)`

Shows a text input dialog and returns the entered text or `None`.

#### `await ctx.ui.editor(title, prefill="")`

Shows a multi-line editor and returns the edited text or `None`.

### Notifications and UI state

#### `ctx.ui.notify(message, level="info")`

Levels currently supported by the UI include:

- `info`
- `success`
- `warning`
- `error`
- `muted`

#### `ctx.ui.set_status(key, text)`

Adds or clears a footer status entry.

#### `ctx.ui.set_working_message(message=None)`

Changes the loader text shown while the agent is running.

#### `ctx.ui.set_hidden_thinking_label(label=None)`

Changes the label used when thinking blocks are collapsed.

#### `ctx.ui.set_editor_text(text)` / `ctx.ui.get_editor_text()`

Set or retrieve the current editor contents.

#### `ctx.ui.get_all_themes()` / `ctx.ui.set_theme(name)`

Inspect or switch themes.

#### `ctx.ui.get_tools_expanded()` / `ctx.ui.set_tools_expanded(expanded)`

Get or change whether tool output is expanded.

#### `ctx.ui.set_title(title)`

Sets the terminal title.

### Lower-level UI methods

These exist, but most extensions will not need them:

- `add_message(...)`
- `remove_message(...)`
- `show_selector(...)`
- `update_footer()`
- `clear_chat()`
- `stop()`
- `shutdown()`
- `is_idle()`
- `abort_current()`
- `get_current_system_prompt()`
- `request_render()`
- `set_agent(...)`
- `set_hide_thinking_block(...)`

Prefer the higher-level APIs on `ExtensionContext` and the normal dialog methods when possible.

---

## Events

Register handlers with:

```python
@pana.on("event_name")
async def handler(event, ctx):
    ...
```

Handlers may be sync or async.

### Important behavior

- handlers run in extension load order
- exceptions are logged and swallowed
- different events have different return semantics

## Event list

### `session_start`

Fired once when the session begins.

Event type:

```python
SessionStartEvent
```

Example:

```python
@pana.on("session_start")
async def on_start(event, ctx):
    ctx.ui.notify("Loaded", "info")
```

---

### `session_shutdown`

Fired before the application exits.

Use this for cleanup.

```python
@pana.on("session_shutdown")
async def on_shutdown(event, ctx):
    ctx.ui.notify("Goodbye", "muted")
```

---

### `input`

Fired when the user submits text, before slash-command dispatch and before the agent runs.

Event type:

```python
@dataclass
class InputEvent:
    text: str
    source: str = "interactive"
```

Return values:

- `{"action": "continue"}` or `None`: keep going unchanged
- `{"action": "transform", "text": "..."}`: replace the input text
- `{"action": "handled"}`: stop processing completely

#### Semantics

`input` handlers are chained.

- later handlers see transformed text from earlier handlers
- the first handler returning `handled` stops processing

Example:

```python
@pana.on("input")
def rewrite_shortcut(event, ctx):
    if event.text.startswith("? "):
        return {
            "action": "transform",
            "text": f"Answer briefly: {event.text[2:]}",
        }
    return None
```

---

### `before_agent_start`

Fired after input processing, just before the agent loop begins.

Event type:

```python
@dataclass
class BeforeAgentStartEvent:
    prompt: str
    system_prompt: str = ""
```

Return value:

```python
{"system_prompt": "..."}
```

#### Semantics

Handlers are chained in load order.

- each handler receives the current `system_prompt`
- if a handler returns `system_prompt`, that becomes the value seen by later handlers
- the final value is used only for the current run

Example:

```python
@pana.on("before_agent_start")
def add_rule(event, ctx):
    current = event.system_prompt.strip()
    extra = "Always mention important risks explicitly."
    if current:
        return {"system_prompt": f"{current}\n\n{extra}"}
    return {"system_prompt": extra}
```

---

### `agent_start`

Fired once per user prompt, before the main loop starts.

Event type:

```python
@dataclass
class AgentStartEvent:
    prompt: str
```

---

### `agent_end`

Fired once per user prompt after the run completes.

Event type:

```python
@dataclass
class AgentEndEvent:
    prompt: str
```

---

### `turn_start`

Fired at the start of each model turn.

Event type:

```python
@dataclass
class TurnStartEvent:
    turn_index: int
```

---

### `turn_end`

Fired after each round of tool execution completes.

Event type:

```python
@dataclass
class TurnEndEvent:
    turn_index: int
```

---

### `tool_call`

Fired before a tool executes.

Event type:

```python
@dataclass
class ToolCallEvent:
    tool_name: str
    input: dict[str, object]
    tool_call_id: str | None = None
```

Return value:

```python
{"block": True, "reason": "..."}
```

#### Semantics

- `event.input` is mutable
- mutations affect the real tool call
- later handlers see changes made by earlier handlers
- the first blocking handler stops execution

Example: block dangerous bash commands.

```python
@pana.on("tool_call")
def guard_rm(event, ctx):
    if event.tool_name != "bash":
        return None

    command = str(event.input.get("command", ""))
    if "rm -rf /" in command:
        return {"block": True, "reason": "rm -rf / is not allowed"}
    return None
```

Example: patch tool arguments.

```python
@pana.on("tool_call")
def rewrite_read_path(event, ctx):
    if event.tool_name == "read" and event.input.get("path") == "README":
        event.input["path"] = "README.md"
```

---

### `tool_result`

Fired after a tool finishes, before the result is returned to the model.

Event type:

```python
@dataclass
class ToolResultEvent:
    tool_name: str
    input: dict[str, object]
    content: str
    details: object | None = None
    is_error: bool = False
    tool_call_id: str | None = None
```

Return value may contain any subset of:

```python
{
    "content": "...",
    "details": ...,
    "is_error": True,
}
```

#### Semantics

`tool_result` behaves like middleware.

- each handler sees the latest result after earlier modifications
- omitted fields are preserved
- handlers can change the tool output seen by the model

Example:

```python
@pana.on("tool_result")
def add_suffix(event, ctx):
    if event.tool_name == "greet":
        return {"content": event.content + " 👋"}
    return None
```

---

### `tool_execution_start`

Fired immediately before a tool begins executing.

Event type:

```python
@dataclass
class ToolExecutionStartEvent:
    tool_name: str
    args: dict[str, object]
    tool_call_id: str | None = None
```

This is useful for logging or UI updates.

---

### `tool_execution_end`

Fired immediately after a tool finishes executing.

Event type:

```python
@dataclass
class ToolExecutionEndEvent:
    tool_name: str
    args: dict[str, object]
    result: ToolExecutionResult
    tool_call_id: str | None = None
```

This is useful for post-processing, notifications, and instrumentation.

---

## Tools

Custom tools are callable by the model.

### Basic tool registration

```python
from pana.app.extensions.api import ToolDefinition


async def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone by name.

    Args:
        name: Name to greet.
        greeting: Greeting phrase.
    """
    return f"{greeting}, {name}!"


pana.register_tool(ToolDefinition(
    name="greet",
    description="Greet someone by name",
    execute=greet,
))
```

### ToolDefinition fields

```python
@dataclass
class ToolDefinition:
    name: str
    execute: ToolExecuteCallable
    description: str = ""
    label: str = ""
    parameters_schema: dict[str, object] | None = None
    prompt_snippet: str | None = None
```

#### `name`

Tool name used by the model.

#### `execute`

The function that runs the tool.

It may be sync or async.

It may return either:

- a plain `str`, or
- a `ToolExecutionResult`

#### `description`

Human-readable description shown to the model.

#### `label`

Currently available on the API for future/UI use. You can set it, but today the most important fields are `name`, `description`, `execute`, `parameters_schema`, and `prompt_snippet`.

#### `parameters_schema`

Optional explicit JSON schema for tool arguments.

If omitted, Pana derives a schema from the function signature and type annotations.

#### `prompt_snippet`

Optional short description used in the system prompt tool listing.

If omitted, Pana falls back to `description`.

---

## Tool parameters

### Option 1: inferred from the function signature

This is the simplest option.

```python
async def greet(name: str, greeting: str = "Hello") -> str:
    ...
```

Pana will infer a JSON schema from:

- parameter names
- type annotations
- whether parameters have defaults
- argument descriptions in the docstring `Args:` section

Supported primitive mappings include:

- `str -> string`
- `int -> integer`
- `float -> number`
- `bool -> boolean`
- `T | None` / `Optional[T]` -> optional property of the inner type

If a type is unknown, Pana falls back to `string`.

### Option 2: explicit `parameters_schema`

Use this when you need more control.

```python
pana.register_tool(ToolDefinition(
    name="greet",
    description="Greet someone by name",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name to greet"},
            "greeting": {"type": "string", "description": "Greeting phrase"},
        },
        "required": ["name"],
    },
    execute=greet,
))
```

Use explicit schema when you need:

- stricter control over required fields
- better descriptions
- nested object shapes
- enum-like constraints
- schema compatibility across future tool refactors

---

## Tool return values

### Returning a string

The simplest form:

```python
async def hello(name: str) -> str:
    return f"Hello, {name}!"
```

### Returning `ToolExecutionResult`

Use this when you want metadata or explicit error state.

```python
from pana.app.extensions.api import ToolExecutionResult


async def hello(name: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        content=f"Hello, {name}!",
        details={"name": name},
        is_error=False,
    )
```

### Error handling

If your tool raises an exception, Pana converts it into:

```python
ToolExecutionResult(
    content=f"Error: {exc}",
    is_error=True,
)
```

You can also return an error explicitly:

```python
return ToolExecutionResult(
    content="Error: invalid input",
    is_error=True,
)
```

---

## Tool overriding

If multiple tools have the same name, the last loaded one wins.

That means an extension can override a built-in tool such as:

- `read`
- `edit`
- `write`
- `bash`

Example:

```python
async def read(path: str, offset: int | None = None, limit: int | None = None) -> str:
    return f"Custom read for {path}"

pana.register_tool(ToolDefinition(
    name="read",
    description="Custom read override",
    execute=read,
))
```

Be careful: if you override a built-in tool, your tool should still behave sensibly for the model.

---

## Commands

Slash commands are for user-invoked actions such as `/hello`.

### Basic command registration

```python
from pana.app.extensions.api import CommandDefinition


async def hello_handler(args: str, ctx) -> None:
    target = args.strip() or "world"
    ctx.ui.notify(f"Hello, {target}!", "info")


pana.register_command("hello", CommandDefinition(
    description="Say hello",
    handler=hello_handler,
))
```

### CommandDefinition

```python
@dataclass
class CommandDefinition:
    description: str
    handler: CommandHandler
```

The handler receives:

- `args: str`
- `ctx: ExtensionContext`

### Command name conflicts

Built-in commands are registered first.

If multiple extension commands use the same name:

- the first one keeps the original name
- later ones are renamed to `name:2`, `name:3`, and so on

So if two extensions both register `hello`, the second may become `/hello:2`.

---

## Source metadata

Internally, Pana tracks source metadata for each extension:

```python
@dataclass(frozen=True)
class SourceInfo:
    path: str
    name: str
    scope: Literal["global", "project", "cli", "unknown"]
```

This is mostly runtime metadata today, but it explains how collisions are resolved and logged.

---

## Full example

```python
from pana.app.extensions.api import (
    CommandDefinition,
    ExtensionAPI,
    ToolDefinition,
    ToolExecutionResult,
)


def setup(pana: ExtensionAPI) -> None:
    @pana.on("session_start")
    async def on_start(event, ctx):
        ctx.ui.notify("Hello extension loaded!", "info")

    @pana.on("session_shutdown")
    async def on_shutdown(event, ctx):
        ctx.ui.notify("Goodbye from hello extension.", "info")

    @pana.on("tool_call")
    def guard_rm(event, ctx):
        if event.tool_name == "bash":
            command = str(event.input.get("command", ""))
            if "rm -rf /" in command:
                return {"block": True, "reason": "rm -rf / is not allowed"}
        return None

    @pana.on("before_agent_start")
    def add_rule(event, ctx):
        extra = "Always end responses with a friendly emoji. 😊"
        current = event.system_prompt.strip()
        if current:
            return {"system_prompt": f"{current}\n\n{extra}"}
        return {"system_prompt": extra}

    async def greet(name: str, greeting: str = "Hello") -> ToolExecutionResult:
        return ToolExecutionResult(
            content=f"{greeting}, {name}!",
            details={"name": name, "greeting": greeting},
        )

    pana.register_tool(ToolDefinition(
        name="greet",
        description="Greet someone by name",
        prompt_snippet="Greet a user in a friendly way",
        execute=greet,
    ))

    async def hello_handler(args: str, ctx) -> None:
        target = args.strip() or "world"
        ctx.ui.notify(f"Hello, {target}!", "info")

    pana.register_command("hello", CommandDefinition(
        description="Say hello to someone",
        handler=hello_handler,
    ))
```

---

## Best practices

### 1. Keep tools focused

Small, well-defined tools are easier for the model to use correctly.

### 2. Use explicit schema when the shape matters

Signature inference is convenient, but `parameters_schema` is better for complex tools.

### 3. Use `ToolExecutionResult` when you need metadata

If you may want post-processing or future rendering/state hooks, return structured results.

### 4. Be careful when mutating tool arguments

`tool_call` can rewrite arguments. That is powerful, but easy to abuse. Keep argument rewriting small and predictable.

### 5. Prefer blocking dangerous actions in `tool_call`

This is the right place for permission gates.

### 6. Keep `before_agent_start` changes additive

If several extensions modify the system prompt, simple additive behavior is easier to reason about.

### 7. Handle missing `ctx.model`

There may be no active model yet.

```python
if ctx.model is not None:
    ctx.ui.notify(ctx.model.model_name, "muted")
```

### 8. Use timeouts and cancellation where appropriate

If you run external work, pass `ctx.signal` where possible.

```python
result = await pana.exec("git", ["status"], signal=ctx.signal, timeout=5)
```

### 9. Clean up on `session_shutdown`

If your extension creates background resources, close them there.

---

## Limitations of the current extension system

These are important to know when designing an extension.

### No hot reload API

Extensions are loaded at startup. There is currently no `/reload`-style public extension runtime reload flow.

### No dedicated persistence API yet

There is currently no public extension state storage API. If you need persistent state, you will need to manage it yourself for now.

### No custom message rendering API yet

Extensions can influence behavior and UI through events and `ctx.ui`, but there is not yet a first-class custom message rendering system.

### No shortcut/flag/provider extension APIs yet

The current public system focuses on:

- events
- tools
- commands
- UI interaction
- shell execution

---

## Troubleshooting

### My extension is not loading

Check:

- the file is in a supported location
- the module exports `setup(pana)`
- the file is valid Python
- directory-based extensions are Python packages containing `__init__.py`

### My tool arguments are wrong

Check:

- your function signature type annotations
- your docstring `Args:` formatting
- whether `parameters_schema` would be clearer
- whether another extension is mutating the tool call in `tool_call`

### My command name changed

A name collision likely occurred. Later conflicting commands are renamed to `:2`, `:3`, etc.

### My handler raised an exception and Pana kept running

This is expected. Extension handler errors are logged and swallowed so that a broken extension does not crash the app.

---

## Quick reference

### Create an extension

```python
def setup(pana: ExtensionAPI) -> None:
    ...
```

### Register an event handler

```python
@pana.on("session_start")
async def handler(event, ctx):
    ...
```

### Register a tool

```python
pana.register_tool(ToolDefinition(
    name="my_tool",
    description="...",
    execute=my_tool,
))
```

### Register a command

```python
pana.register_command("mycmd", CommandDefinition(
    description="...",
    handler=my_handler,
))
```

### Run a shell command

```python
result = await pana.exec("git", ["status"])
```

### Show a notification

```python
ctx.ui.notify("Done", "success")
```

### Block a tool call

```python
return {"block": True, "reason": "Not allowed"}
```

### Transform input

```python
return {"action": "transform", "text": "..."}
```

### Return a structured tool result

```python
return ToolExecutionResult(content="ok", details={"x": 1})
```
