# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_run_operator``: validated execution of any Blender operator.

This is the long-tail escape hatch that removes the need to add a new Rust
tool for every ``bpy.ops`` function: parameters are validated and coerced from
the operator's own RNA, and failures include poll/context diagnostics.

It also absorbs the former primitive wrapper: ``primitive_type`` selects a
creation operator, while ``name``/``collection``/``properties`` post-process
the created object.
"""

from __future__ import annotations

import bpy

from .. import catalogs, registry, rna

# Semantic primitive aliases only; geometry parameters still come from operator RNA.
_PRIMITIVE_ALIASES = {
    "box": "mesh.primitive_cube_add",
    "sphere": "mesh.primitive_uv_sphere_add",
    "uvsphere": "mesh.primitive_uv_sphere_add",
    "icosphere": "mesh.primitive_ico_sphere_add",
    "bezier": "curve.primitive_bezier_curve_add",
    "beziercurve": "curve.primitive_bezier_curve_add",
    "curvebezier": "curve.primitive_bezier_curve_add",
    "beziercircle": "curve.primitive_bezier_circle_add",
    "curvecircle": "curve.primitive_bezier_circle_add",
    "text": "object.text_add",
    "empty": "object.empty_add",
    "camera": "object.camera_add",
    "light": "object.light_add",
}


def _operator_exists(path):
    module, _, name = path.partition(".")
    parent = getattr(bpy.ops, module, None)
    return parent is not None and name and hasattr(parent, name)


def resolve_primitive(primitive_type):
    key = rna.norm(primitive_type)
    if key in _PRIMITIVE_ALIASES:
        return _PRIMITIVE_ALIASES[key]

    raw = str(primitive_type).strip().lower()
    for candidate in (
        f"mesh.primitive_{raw}_add",
        f"curve.primitive_{raw}_add",
        f"object.{raw}_add",
    ):
        if _operator_exists(candidate):
            return candidate

    kinds = catalogs.primitive_kinds()["primitives"]
    matches = [item for item in kinds if key in rna.norm(item["kind"])]
    if len(matches) == 1:
        return matches[0]["operator"]

    raise KeyError(
        f"Unknown primitive_type '{primitive_type}'. Available kinds: "
        f"{sorted({item['kind'] for item in kinds})}"
    )


def run(args):
    path = args.get("operator") or args.get("path")
    if not path:
        primitive_type = args.get("primitive_type")
        if not primitive_type:
            raise ValueError("Provide 'operator' or 'primitive_type'")
        path = resolve_primitive(primitive_type)

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
        name=args.get("name"),
        collection=args.get("collection"),
        properties=args.get("properties"),
        location=args.get("location"),
        rotation=args.get("rotation"),
        scale=args.get("scale"),
    )


registry.register(
    name="blender_run_operator",
    handler=run,
    description=(
        "Run ANY Blender operator by path (e.g. 'object.shade_smooth', "
        "'mesh.primitive_grid_add', 'curve.primitive_bezier_curve_add'), or use "
        "'primitive_type' for semantic primitive creation. Parameters are validated "
        "against the operator's live RNA; unknown keys are rejected with suggestions, "
        "enums accept identifiers or display names, and datablock pointers accept names. "
        "Post-processing supports name, collection, properties, location, rotation "
        "(degrees) and scale."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operator": {
                "type": "string",
                "description": "Operator path, e.g. 'mesh.primitive_ico_sphere_add' or 'MESH_OT_primitive_ico_sphere_add'.",
            },
            "primitive_type": {
                "type": "string",
                "description": (
                    "Semantic primitive kind (cube, sphere, ico_sphere, cylinder, cone, "
                    "torus, plane, circle, grid, monkey, text, curve_bezier, curve_circle, "
                    "empty, camera, light, or any operator-derived kind). "
                    "Live list: blender_describe(target='primitives')."
                ),
            },
            "parameters": {
                "type": "object",
                "description": "Operator RNA parameters, e.g. {'radius': 1.5, 'subdivisions': 3}.",
            },
            "name": {
                "type": "string",
                "description": "Rename the created object after the operator runs.",
            },
            "collection": {
                "type": "string",
                "description": "Move the created object into this collection (created if missing).",
            },
            "properties": {
                "type": "object",
                "description": (
                    "Post-apply properties to the created object or its data, e.g. "
                    "{'body': 'Hello'} for text or {'energy': 250, 'color': [1,0.5,0.2]} "
                    "for lights."
                ),
            },
            "location": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Convenience location; merged into operator params when supported.",
            },
            "rotation": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Convenience Euler rotation in degrees.",
            },
            "scale": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Convenience scale; merged into operator params when supported.",
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
        "anyOf": [{"required": ["operator"]}, {"required": ["primitive_type"]}],
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
