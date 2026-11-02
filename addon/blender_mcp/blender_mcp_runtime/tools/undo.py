# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_undo``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy

def run_undo(args):
    try:
        res = bpy.ops.ed.undo()
        return {"status": "ok", "message": f"Undo executed successfully ({res})"}
    except Exception as ex:
        return {"status": "error", "message": f"Failed to undo: {ex}"}

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_undo", run_undo)
