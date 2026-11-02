# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_set``: generic RNA property writes.

This is the consolidation tool that replaces most one-off "configure X"
handlers.  It resolves a datablock/path expression and applies any RNA property
through the same coercion layer used by every other tool.
"""

from __future__ import annotations

import bpy
import math

from .. import registry, rna


def run(args):
    target = args.get("target")
    if not target:
        raise ValueError("Argument 'target' is required")

    root = rna.resolve_target(target)
    path = args.get("path") or ""
    undo = bool(args.get("undo", True))

    properties = args.get("properties")
    if isinstance(properties, dict):
        node = rna.resolve_path(root, path) if path else root
        if undo:
            try:
                bpy.ops.ed.undo_push(message="MCP Set Property")
            except Exception:
                pass
        result = rna.apply_properties(node, properties)
        ok = not result.get("errors") and not result.get("unknown")
        return {
            "status": "ok" if ok else "error",
            "target": str(target),
            "path": path,
            "resolved": getattr(node, "name", type(node).__name__),
            **result,
        }

    if "value" not in args:
        raise ValueError("Provide 'properties' (batch) or 'value' (single property)")
    if not path:
        raise ValueError("Argument 'path' is required when setting a single 'value'")

    parent, leaf = rna.resolve_path_with_leaf(root, path)
    prop, identifier, _score = rna.find_property(parent, leaf)
    if prop is None:
        options = (
            [item.identifier for item in parent.bl_rna.properties]
            if hasattr(parent, "bl_rna")
            else []
        )
        raise KeyError(
            f"Unknown property '{leaf}'. Did you mean: {rna.suggest(leaf, options)}"
        )

    value = args["value"]
    if (
        args.get("unit") == "degrees"
        and prop.type == "FLOAT"
        and getattr(prop, "subtype", "") == "EULER"
    ):
        if not isinstance(value, (list, tuple)):
            raise ValueError("'degrees' unit expects a 3-value rotation array")
        value = [math.radians(float(item)) for item in value]

    if undo:
        try:
            bpy.ops.ed.undo_push(message="MCP Set Property")
        except Exception:
            pass

    result = rna.apply_properties(parent, {identifier: value})
    ok = not result.get("errors") and not result.get("unknown")
    return {
        "status": "ok" if ok else "error",
        "target": str(target),
        "path": path,
        "property": identifier,
        **result,
    }


registry.register(
    name="blender_set",
    handler=run,
    description=(
        "Set any Blender RNA property through a uniform path resolver. Examples: "
        "target='object:RustCube', path='location', value=[1,2,3]; "
        "target='object:RustCube', path='rotation_euler', value=[90,0,0], unit='degrees'; "
        "target='material:MetallicBlue', "
        "path='node_tree.nodes[Principled BSDF].inputs[Base Color].default_value', value='#FF5500'; "
        "target='scene.render', properties={'engine':'CYCLES','resolution_x':1920}; "
        "target='modifier:RustCube/Subsurf', properties={'levels':2}. "
        "Enums accept identifiers or display names; pointers accept datablock names; "
        "colors accept hex strings. Use blender_describe to discover paths and enums."
    ),
    input_schema={
        "type": "object",
        "required": ["target"],
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "Root target: scene, render, world, view_layer, object:NAME, "
                    "object_data:NAME, modifier:OBJECT/MODIFIER, material:NAME, "
                    "node:OWNER/NODE, nodetree:NAME, light:NAME, camera:NAME, "
                    "collection:NAME, or any bpy.data ID type."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Relative RNA path. Examples: 'location', "
                    "'modifiers[Subsurf].levels', "
                    "'node_tree.nodes[Principled BSDF].inputs[Base Color].default_value', "
                    "'render.engine'."
                ),
            },
            "properties": {
                "type": "object",
                "description": "Batch-set properties on the resolved target.",
            },
            "value": {
                "description": "Single property value (used with 'path').",
            },
            "unit": {
                "type": "string",
                "enum": ["native", "degrees"],
                "default": "native",
                "description": "For Euler rotation properties, 'degrees' converts to radians.",
            },
            "undo": {
                "type": "boolean",
                "default": True,
                "description": "Push an undo step before applying.",
            },
        },
        "anyOf": [{"required": ["properties"]}, {"required": ["value"]}],
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
