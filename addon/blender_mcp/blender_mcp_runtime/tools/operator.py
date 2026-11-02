# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_run_operator``: validated execution of any Blender operator.

This is the long-tail escape hatch that removes the need to add a new Rust
tool for every ``bpy.ops`` function: parameters are validated and coerced from
the operator's own RNA, and failures include poll/context diagnostics.
"""

from __future__ import annotations

from .. import registry, rna


def run(args):
    path = args.get("operator") or args.get("path")
    if not path:
        raise ValueError("Argument 'operator' is required (e.g. 'mesh.primitive_cube_add')")

    parameters = args.get("parameters")
    if parameters is None:
        parameters = args.get("params", {})
    if not isinstance(parameters, dict):
        raise ValueError("Argument 'parameters' must be an object")

    return rna.run_operator(
        path,
        parameters,
        undo=bool(args.get("undo", True)),
        select=args.get("select"),
        active=args.get("active"),
        context=args.get("context"),
    )


registry.register(
    name="blender_run_operator",
    handler=run,
    description=(
        "Run ANY Blender operator by path (e.g. 'object.shade_smooth', "
        "'mesh.primitive_grid_add', 'curve.primitive_bezier_curve_add'). Parameters are "
        "validated against the operator's live RNA; unknown keys are rejected with "
        "suggestions, enums accept identifiers or display names, and datablock pointers "
        "accept names. Use blender_describe(target='operator') first to discover parameters."
    ),
    input_schema={
        "type": "object",
        "required": ["operator"],
        "properties": {
            "operator": {
                "type": "string",
                "description": "Operator path, e.g. 'mesh.primitive_ico_sphere_add' or 'MESH_OT_primitive_ico_sphere_add'.",
            },
            "parameters": {
                "type": "object",
                "description": "Operator RNA parameters, e.g. {\"radius\": 1.5, \"subdivisions\": 3}.",
            },
            "undo": {
                "type": "boolean",
                "default": True,
                "description": "Push an undo step before execution.",
            },
            "select": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Optional object name(s) to select before running.",
            },
            "active": {
                "type": "string",
                "description": "Optional active object name before running.",
            },
            "context": {
                "type": "object",
                "description": "Optional context override hints: object, active_object, selected_objects, area_type.",
            },
        },
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
