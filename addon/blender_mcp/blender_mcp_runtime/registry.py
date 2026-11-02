# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tool registry for the adaptive Blender runtime.

A tool is a small Python handler plus an MCP JSON schema.  Rust no longer
needs to know the parameter list of every tool: it asks this registry for the
catalog (``tools/list``) and dispatches by name.
"""

from __future__ import annotations

import json
import os
import traceback

_REGISTRY = {}
_VALID_PROFILES = ("core", "full")
_PROFILE = os.environ.get("BLENDER_MCP_TOOL_PROFILE", "full").strip().lower()
if _PROFILE not in _VALID_PROFILES:
    _PROFILE = "full"


def set_profile(name):
    """Select the advertised tool surface. Explicit tools/call still works."""
    global _PROFILE
    profile = str(name or "full").strip().lower()
    if profile not in _VALID_PROFILES:
        raise ValueError(f"Unknown tool profile '{name}'. Valid: {list(_VALID_PROFILES)}")
    _PROFILE = profile
    return _PROFILE


def get_profile():
    return _PROFILE


def register(
    name,
    handler,
    description,
    input_schema,
    annotations=None,
    profiles=("core", "full"),
    deprecated=False,
    replaced_by=None,
):
    _REGISTRY[name] = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": annotations or {},
        "profiles": tuple(profiles),
        "deprecated": bool(deprecated),
        "replaced_by": tuple(replaced_by or ()),
        "handler": handler,
    }
    return _REGISTRY[name]


def get(name):
    return _REGISTRY.get(name)


def _materialize(spec):
    schema = spec["inputSchema"]
    if callable(schema):
        schema = schema()

    description = spec["description"]
    annotations = dict(spec["annotations"])
    if spec["deprecated"]:
        replacement = ", ".join(spec["replaced_by"])
        description += f" [DEPRECATED - use {replacement}]" if replacement else " [DEPRECATED]"
        annotations.setdefault("deprecated", True)
        if spec["replaced_by"]:
            annotations.setdefault("replacedBy", list(spec["replaced_by"]))

    return {
        "name": spec["name"],
        "description": description,
        "inputSchema": schema,
        "annotations": annotations,
        "deprecated": spec["deprecated"],
        "replacedBy": list(spec["replaced_by"]),
        "profiles": list(spec["profiles"]),
    }


def list_tools(profile=None):
    """Return MCP ``Tool`` definitions for the selected profile."""
    selected = str(profile or _PROFILE).strip().lower()
    if selected not in _VALID_PROFILES:
        selected = "full"
    return [
        _materialize(spec)
        for spec in _REGISTRY.values()
        if selected == "full" or selected in spec["profiles"]
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
    "set_profile",
    "get_profile",
    "list_tools",
    "list_tools_json",
    "dispatch",
    "dispatch_json",
]
