# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Embedded adaptive runtime for Blender MCP.

The Rust extension owns transport and dispatch; all Blender knowledge lives in
this Python package.  The module is imported once and cached by ``sys.modules``,
so catalogs and RNA caches persist across MCP calls.
"""

from . import catalogs, rna
from .registry import dispatch, dispatch_json, get, list_tools, list_tools_json, register
from . import tools as _tools  # noqa: F401  (side effect: registers handlers)

__all__ = [
    "dispatch",
    "dispatch_json",
    "get",
    "list_tools",
    "list_tools_json",
    "register",
    "rna",
    "catalogs",
]
