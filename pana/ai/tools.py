"""Generate OpenAI-compatible tool schemas from Python functions."""

from __future__ import annotations

import inspect
import re
import types
from collections.abc import Callable
from typing import Union, get_args, get_origin, get_type_hints

from pana.ai.types import ToolDef

_PY_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _is_optional(annotation: type) -> tuple[bool, type]:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return True, non_none[0]
    return False, annotation


def _python_type_to_json_type(annotation: type) -> str:
    optional, inner = _is_optional(annotation)
    if optional:
        return _PY_TYPE_TO_JSON.get(inner, "string")
    return _PY_TYPE_TO_JSON.get(annotation, "string")


def _parse_args_from_docstring(docstring: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    in_args = False
    current_name: str | None = None
    current_lines: list[str] = []

    for line in docstring.splitlines():
        stripped = line.strip()

        if stripped.lower().startswith("args:"):
            in_args = True
            continue

        if in_args:
            if stripped == "" or (not stripped.startswith(" ") and not line.startswith(" ")):
                if not stripped.startswith(" ") and ":" in stripped and current_name is None:
                    pass
                if stripped and not re.match(r"^\s", line) and current_name is not None:
                    if current_name and current_lines:
                        descriptions[current_name] = " ".join(current_lines).strip()
                    break

            m = re.match(r"^\s+(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)", line)
            if m:
                if current_name and current_lines:
                    descriptions[current_name] = " ".join(current_lines).strip()
                current_name = m.group(1)
                current_lines = [m.group(2)] if m.group(2) else []
            elif current_name and stripped:
                current_lines.append(stripped)

    if current_name and current_lines:
        descriptions[current_name] = " ".join(current_lines).strip()

    return descriptions


def function_to_tool_def(fn: Callable) -> ToolDef:
    """Convert a Python function into a ToolDef with JSON Schema parameters."""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    docstring = inspect.getdoc(fn) or ""

    description_lines = []
    for line in docstring.splitlines():
        if line.strip().lower().startswith("args:"):
            break
        description_lines.append(line)
    description = "\n".join(description_lines).strip()

    arg_descriptions = _parse_args_from_docstring(docstring)

    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        annotation = hints.get(name, str)
        optional, _ = _is_optional(annotation)
        json_type = _python_type_to_json_type(annotation)

        prop: dict[str, str] = {"type": json_type}
        if name in arg_descriptions:
            prop["description"] = arg_descriptions[name]

        properties[name] = prop

        has_default = param.default is not inspect.Parameter.empty
        if not optional and not has_default:
            required.append(name)

    parameters = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required

    return ToolDef(
        name=fn.__name__,
        description=description,
        parameters=parameters,
    )
