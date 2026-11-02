# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Blender MCP (Rust) Extension
High-performance embedded MCP server for LLMs & AI agents.
"""

bl_info = {
    "name": "Blender MCP (Rust)",
    "author": "Blender MCP Community",
    "version": (0, 3, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > MCP Tab",
    "description": "High-performance Rust-powered MCP server providing semantic tools for AI agents",
    "category": "Development",
}

import sys
import os
import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty, FloatProperty

# Ensure the addon directory is on sys.path so blender_mcp_core.so can be imported
_addon_dir = os.path.dirname(os.path.abspath(__file__))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

try:
    import blender_mcp_core
    _CORE_AVAILABLE = True
except ImportError as ex:
    _CORE_AVAILABLE = False
    _IMPORT_ERROR = str(ex)


def _timer_callback():
    if not _CORE_AVAILABLE or not blender_mcp_core.is_running():
        return None

    try:
        prefs = bpy.context.preferences.addons.get(__package__, None)
        active_int = prefs.preferences.active_interval if prefs else 0.005
        idle_int = prefs.preferences.idle_interval if prefs else 0.05

        dispatched = blender_mcp_core.poll_tick(16)
        return active_int if dispatched > 0 else idle_int
    except Exception as ex:
        print(f"[Blender MCP] Timer tick error: {ex}")
        return 0.05


class BLMCP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    host: StringProperty(
        name="Host",
        default="127.0.0.1",
        description="Host address for MCP server to bind to",
    )
    port: IntProperty(
        name="Port",
        default=8765,
        min=1024,
        max=65535,
        description="Port for MCP server",
    )
    autostart: BoolProperty(
        name="Auto-start Server",
        default=True,
        description="Automatically start the MCP server when Blender loads",
    )
    active_interval: FloatProperty(
        name="Active Poll Interval (s)",
        default=0.005,
        min=0.001,
        max=0.1,
        description="Main loop timer interval when processing incoming tasks",
    )
    idle_interval: FloatProperty(
        name="Idle Poll Interval (s)",
        default=0.05,
        min=0.01,
        max=1.0,
        description="Main loop timer interval when idle",
    )

    def draw(self, context):
        layout = self.layout

        if not _CORE_AVAILABLE:
            layout.alert = True
            layout.label(text=f"Failed to load blender_mcp_core.so: {_IMPORT_ERROR}", icon="ERROR")
            return

        is_running = blender_mcp_core.is_running()

        box = layout.box()
        row = box.row(align=True)
        if is_running:
            row.label(text=f"Server Running: http://{self.host}:{self.port}/mcp", icon="CHECKMARK")
            row.operator("blmcp.server_stop", text="Stop Server", icon="CANCEL")
        else:
            row.label(text="Server Stopped", icon="X")
            row.operator("blmcp.server_start", text="Start Server", icon="PLAY")

        col = layout.column()
        col.prop(self, "host")
        col.prop(self, "port")
        col.prop(self, "autostart")
        col.prop(self, "active_interval")
        col.prop(self, "idle_interval")


class BLMCP_OT_server_start(bpy.types.Operator):
    bl_idname = "blmcp.server_start"
    bl_label = "Start MCP Server"
    bl_description = "Start the embedded Rust MCP server"

    def execute(self, context):
        if not _CORE_AVAILABLE:
            self.report({"ERROR"}, f"Core module not loaded: {_IMPORT_ERROR}")
            return {"CANCELLED"}

        prefs = context.preferences.addons[__package__].preferences
        try:
            blender_mcp_core.start_server(prefs.host, prefs.port)
            if not bpy.app.timers.is_registered(_timer_callback):
                bpy.app.timers.register(_timer_callback, first_interval=prefs.active_interval, persistent=True)
            self.report({"INFO"}, f"Blender MCP started on http://{prefs.host}:{prefs.port}/mcp")
            return {"FINISHED"}
        except Exception as ex:
            self.report({"ERROR"}, f"Failed to start server: {ex}")
            return {"CANCELLED"}


class BLMCP_OT_server_stop(bpy.types.Operator):
    bl_idname = "blmcp.server_stop"
    bl_label = "Stop MCP Server"
    bl_description = "Stop the embedded Rust MCP server"

    def execute(self, context):
        if not _CORE_AVAILABLE:
            return {"CANCELLED"}

        try:
            blender_mcp_core.stop_server()
            if bpy.app.timers.is_registered(_timer_callback):
                bpy.app.timers.unregister(_timer_callback)
            self.report({"INFO"}, "Blender MCP server stopped.")
            return {"FINISHED"}
        except Exception as ex:
            self.report({"ERROR"}, f"Failed to stop server: {ex}")
            return {"CANCELLED"}


class VIEW3D_PT_blender_mcp(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Blender MCP'
    bl_label = 'MCP Agent Bridge'

    def draw(self, context):
        layout = self.layout
        if not _CORE_AVAILABLE:
            layout.alert = True
            layout.label(text="Core .so missing", icon="ERROR")
            return

        is_running = blender_mcp_core.is_running()
        prefs = context.preferences.addons[__package__].preferences

        box = layout.box()
        if is_running:
            box.label(text="Status: Active", icon="RADIOBUT_ON")
            box.label(text=f"http://{prefs.host}:{prefs.port}/mcp")
            box.operator("blmcp.server_stop", text="Stop Server", icon="CANCEL")
        else:
            box.label(text="Status: Inactive", icon="RADIOBUT_OFF")
            box.operator("blmcp.server_start", text="Start Server", icon="PLAY")

        box2 = layout.box()
        box2.label(text="Adaptive Tools: 12 Available", icon="TOOL_SETTINGS")
        box2.label(text="Describe, Run Operator, Inspect,")
        box2.label(text="Primitives, Transform, Modifiers,")
        box2.label(text="Materials, Nodes, Setup, Capture,")
        box2.label(text="Script, Undo")


classes = (
    BLMCP_Preferences,
    BLMCP_OT_server_start,
    BLMCP_OT_server_stop,
    VIEW3D_PT_blender_mcp,
)


def _autostart():
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        if prefs.autostart and not bpy.app.background:
            bpy.ops.blmcp.server_start()
    except Exception:
        pass
    return None


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Delay autostart by 0.5s to let Blender UI finish initializing
    bpy.app.timers.register(_autostart, first_interval=0.5)


def unregister():
    if _CORE_AVAILABLE and blender_mcp_core.is_running():
        try:
            blender_mcp_core.stop_server()
        except Exception:
            pass

    if bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.unregister(_timer_callback)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
