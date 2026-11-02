# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tool registry for the adaptive Blender runtime.

A tool is a small Python handler plus an MCP JSON schema.  Rust no longer
needs to know the parameter list of every tool: it asks this registry for the
catalog (``tools/list``) and dispatches by name.
"""

from __future__ import annotations

import json
import traceback

_REGISTRY = {}


def register(name, handler, description, input_schema, annotations=None):
    _REGISTRY[name] = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": annotations or {},
        "handler": handler,
    }
    return _REGISTRY[name]


def get(name):
    return _REGISTRY.get(name)


def list_tools():
    """Return MCP ``Tool`` definitions (the Rust side merges these)."""
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
            "annotations": spec["annotations"],
        }
        for spec in _REGISTRY.values()
    ]


def list_tools_json():
    """JSON string variant used by the Rust extension."""
    return json.dumps(list_tools())


def _error(message, **extra):
    payload = {"status": "error", "message": str(message)}
    payload.update(extra)
    return payload


def dispatch(name, args_json):
    """Entry point called by the Rust extension for every runtime tool."""
    try:
        args = json.loads(args_json) if args_json else {}
    except Exception as ex:
        return _error(f"Invalid JSON arguments: {ex}")

    if not isinstance(args, dict):
        return _error("Arguments must be a JSON object")

    spec = _REGISTRY.get(name)
    if spec is None:
        return _error(
            f"Unknown runtime tool '{name}'",
            available=sorted(_REGISTRY.keys()),
        )

    try:
        result = spec["handler"](args)
    except KeyError as ex:
        return _error(ex.args[0] if ex.args else str(ex), traceback=traceback.format_exc())
    except Exception as ex:
        return _error(str(ex), traceback=traceback.format_exc())

    if result is None:
        result = {"status": "ok"}
    if not isinstance(result, dict):
        result = {"status": "ok", "result": result}
    result.setdefault("status", "ok")
    return result


def dispatch_json(name, args_json):
    """FFI boundary: always return a JSON string, even for exotic values."""
    return json.dumps(dispatch(name, args_json), default=str)


__all__ = [
    "register",
    "get",
    "list_tools",
    "list_tools_json",
    "dispatch",
    "dispatch_json",
]
