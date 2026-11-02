# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_execute_script``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
import io
import sys
import time
import math
import mathutils
from mathutils import Vector, Matrix, Euler, Quaternion, Color
import traceback
import json

def run_script(args):
    user_code = args.get("code", "")
    auto_undo = args.get("auto_undo", True)

    if auto_undo:
        try:
            bpy.ops.ed.undo_push(message="MCP Script Execution")
        except Exception:
            pass

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    # Pre-inject high-frequency Blender mathematical & context utilities
    local_vars = {
        "bpy": bpy,
        "C": bpy.context,
        "D": bpy.data,
        "math": math,
        "mathutils": mathutils,
        "Vector": Vector,
        "Matrix": Matrix,
        "Euler": Euler,
        "Quaternion": Quaternion,
        "Color": Color,
        "radians": math.radians,
        "degrees": math.degrees,
        "pi": math.pi,
    }
    start_time = time.perf_counter()

    try:
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        exec(user_code, local_vars)
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        
        result_val = local_vars.get("result", None)
        try:
            json.dumps(result_val)
        except (TypeError, OverflowError):
            result_val = repr(result_val)

        return {
            "status": "ok",
            "result": result_val,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_ms": duration_ms
        }
    except Exception as ex:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return {
            "status": "error",
            "message": str(ex),
            "traceback": traceback.format_exc(),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_ms": duration_ms
        }
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_execute_script", run_script)
