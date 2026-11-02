# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptive primitive creation.

The old implementation was a 60-line ``if primitive_type == ...`` ladder with a
second stale enum in the Rust schema.  Here the semantic name only selects an
operator; every geometric parameter (size, radius, segments, vertices,
major_radius, subdivisions, ...) is validated and coerced from that operator's
own RNA.  New primitives added by Blender or an add-on are usable immediately.
"""

from __future__ import annotations

import bpy
import math
from mathutils import Quaternion

from .. import catalogs, registry, rna

# Only *semantic aliases* live here, never parameter knowledge.
_ALIASES = {
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

_TRANSFORM_KEYS = ("location", "rotation", "scale")


def _operator_exists(path):
    module, _, name = path.partition(".")
    parent = getattr(bpy.ops, module, None)
    return parent is not None and name and hasattr(parent, name)


def _resolve_operator(primitive_type, operator):
    if operator:
        return str(operator)

    if not primitive_type:
        raise ValueError("Provide 'primitive_type' or 'operator'")

    key = rna.norm(primitive_type)
    if key in _ALIASES:
        return _ALIASES[key]

    raw = str(primitive_type).strip().lower()
    for candidate in (
        f"mesh.primitive_{raw}_add",
        f"curve.primitive_{raw}_add",
        f"object.{raw}_add",
    ):
        if _operator_exists(candidate):
            return candidate

    kinds = catalogs.primitive_kinds()["primitives"]
    matches = [
        item for item in kinds
        if key in rna.norm(item["kind"]) or rna.norm(item["kind"]) in key
    ]
    if len(matches) == 1:
        return matches[0]["operator"]

    raise KeyError(
        f"Unknown primitive_type '{primitive_type}'. "
        f"Available kinds: {sorted({item['kind'] for item in kinds})}"
    )


def _kind_of(operator_path, primitive_type):
    text = rna.norm(primitive_type or operator_path)
    for kind in ("light", "camera", "empty", "text"):
        if kind in text:
            return kind
    return "mesh"


def _rotation_degrees(obj):
    if obj.rotation_mode == "QUATERNION":
        euler = obj.rotation_quaternion.to_euler()
    elif obj.rotation_mode == "AXIS_ANGLE":
        quat = Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
        euler = quat.to_euler()
    else:
        euler = obj.rotation_euler
    return [round(math.degrees(value), 2) for value in euler]


def _move_to_collection(obj, collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for owner in list(obj.users_collection):
        if owner != collection:
            owner.objects.unlink(obj)
    return collection.name


def _created_object(run_result):
    for name in run_result.get("created_objects", []):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            return obj
    active = bpy.context.view_layer.objects.active
    if active is not None:
        return active
    if run_result.get("created_objects"):
        return bpy.data.objects.get(run_result["created_objects"][0])
    return None


def create(args):
    primitive_type = args.get("primitive_type")
    operator_path = _resolve_operator(primitive_type, args.get("operator"))
    kind = _kind_of(operator_path, primitive_type)

    extra = args.get("parameters")
    if extra is None:
        extra = args.get("extra", {})
    if not isinstance(extra, dict):
        raise ValueError("Argument 'parameters'/'extra' must be an object")

    params = dict(extra)
    # Legacy semantic keys -> real RNA identifiers (no parameter knowledge).
    if kind == "light" and "light_type" in params:
        params.setdefault("type", params.pop("light_type"))
    if kind == "empty" and "empty_draw_type" in params:
        params.setdefault("type", params.pop("empty_draw_type"))

    table = rna.operator_property_table(operator_path)

    deferred = {}
    op_params = {}
    for key, value in params.items():
        if key in table:
            op_params[key] = value
            continue
        prop, identifier, score = rna.find_property(table, key)
        if prop is not None and score >= 80:
            op_params[identifier] = value
        else:
            # Unknown to the operator: it may be an object/data property that
            # is only resolvable after creation (light size, camera lens, font
            # size, ...).  We defer and validate against real RNA below.
            deferred[key] = value

    # Explicit transforms from the tool's stable contract.
    if args.get("location") is not None:
        location = args["location"]
        (op_params if "location" in table else deferred)["location"] = location
    if args.get("rotation") is not None:
        rotation = [math.radians(float(value)) for value in args["rotation"]]
        (op_params if "rotation" in table else deferred)["rotation"] = rotation
    if args.get("scale") is not None:
        scale = args["scale"]
        (op_params if "scale" in table else deferred)["scale"] = scale

    run_result = rna.run_operator(
        operator_path,
        op_params,
        undo=bool(args.get("undo", True)),
    )
    if run_result.get("status") != "ok":
        return run_result

    obj = _created_object(run_result)
    if obj is None:
        return {
            "status": "error",
            "operator": operator_path,
            "message": "Operator finished but no object was created",
            "operator_result": run_result,
        }

    warnings = list(run_result.get("warnings", []))

    # Apply transforms the operator did not expose (e.g. torus/camera scale).
    transform_deferred = {k: v for k, v in deferred.items() if k in _TRANSFORM_KEYS}
    if transform_deferred:
        applied = rna.apply_properties(obj, transform_deferred)
        warnings.extend(applied.get("warnings", []))
        warnings.extend(applied.get("errors", []))

    # Optional custom name.
    if args.get("name"):
        obj.name = str(args["name"])

    # Resolve remaining parameters against the *created* object and its data.
    remaining = {k: v for k, v in deferred.items() if k not in _TRANSFORM_KEYS}
    post_applied = {}
    unresolved = []

    if "text" in remaining or "body" in remaining:
        body = remaining.pop("text", remaining.pop("body", None))
        if hasattr(obj.data, "body"):
            obj.data.body = str(body)
            post_applied["body"] = str(body)
        else:
            warnings.append("Parameter 'text'/'body' ignored: object has no text body")

    obj_props = {}
    data_props = {}
    for key, value in list(remaining.items()):
        if rna.find_property(obj, key)[0] is not None:
            obj_props[key] = remaining.pop(key)
        elif obj.data is not None and rna.find_property(obj.data, key)[0] is not None:
            data_props[key] = remaining.pop(key)

    if obj_props:
        applied = rna.apply_properties(obj, obj_props)
        post_applied.update(applied.get("applied", {}))
        warnings.extend(applied.get("warnings", []))
        warnings.extend(applied.get("errors", []))
    if data_props:
        applied = rna.apply_properties(obj.data, data_props)
        post_applied.update(applied.get("applied", {}))
        warnings.extend(applied.get("warnings", []))
        warnings.extend(applied.get("errors", []))

    unresolved = sorted(remaining.keys())
    if unresolved:
        candidates = list(table.keys()) + [p.identifier for p in obj.bl_rna.properties]
        if obj.data is not None:
            candidates += [p.identifier for p in obj.data.bl_rna.properties]
        return {
            "status": "error",
            "operator": operator_path,
            "created_object": obj.name,
            "message": (
                f"Object '{obj.name}' was created, but these parameters were not found "
                f"on the operator, object or object data: {unresolved}. "
                f"Did you mean: {rna.suggest(unresolved[0], candidates)}"
            ),
            "valid_parameters": sorted(table.keys()),
            "hint": "The creation is undoable via blender_undo.",
        }

    collection = args.get("collection")
    if collection:
        try:
            _move_to_collection(obj, str(collection))
        except Exception as ex:
            warnings.append(f"Could not move object to collection '{collection}': {ex}")

    return {
        "status": "ok",
        "operator": operator_path,
        "created_object": {
            "name": obj.name,
            "type": obj.type,
            "location": [round(value, 4) for value in obj.location],
            "rotation_euler_deg": _rotation_degrees(obj),
            "scale": [round(value, 4) for value in obj.scale],
            "dimensions": [round(value, 4) for value in obj.dimensions],
            "collection": obj.users_collection[0].name if obj.users_collection else None,
        },
        "applied_parameters": run_result.get("parameters", {}),
        "post_parameters": post_applied,
        "warnings": warnings,
    }


registry.register(
    name="blender_create_primitive",
    handler=create,
    description=(
        "Adaptive primitive creation. 'primitive_type' is a semantic alias (cube, sphere, "
        "cylinder, cone, torus, plane, circle, grid, monkey, text, curve_bezier, "
        "curve_circle, empty, camera, light, or any operator-derived kind); all geometric "
        "parameters are validated against the live creation operator RNA, so new Blender "
        "parameters work without updating this tool. Use blender_describe(target='primitives') "
        "to list available kinds and blender_describe(target='operator', path=...) for parameters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "primitive_type": {
                "type": "string",
                "description": (
                    "Semantic kind (cube, sphere, ico_sphere, cylinder, cone, torus, plane, "
                    "circle, grid, monkey, text, curve_bezier, curve_circle, empty, camera, "
                    "light). Live list: blender_describe(target='primitives')."
                ),
            },
            "operator": {
                "type": "string",
                "description": "Explicit creation operator, e.g. 'mesh.primitive_grid_add'. Overrides primitive_type.",
            },
            "name": {"type": "string", "description": "Custom object name."},
            "location": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [0.0, 0.0, 0.0],
                "description": "World location [x, y, z].",
            },
            "rotation": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [0.0, 0.0, 0.0],
                "description": "Euler rotation in degrees [rx, ry, rz] (converted to radians for Blender).",
            },
            "scale": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [1.0, 1.0, 1.0],
                "description": "Scale [sx, sy, sz].",
            },
            "collection": {
                "type": "string",
                "description": "Target collection; created automatically if missing.",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Operator-specific RNA parameters, e.g. {'radius': 1.5, 'segments': 48} "
                    "or {'major_radius': 2.0, 'minor_radius': 0.3}. Unknown keys are rejected "
                    "with suggestions, never silently ignored."
                ),
            },
            "extra": {
                "type": "object",
                "description": "Deprecated alias for 'parameters'.",
            },
            "undo": {"type": "boolean", "default": True},
        },
        "anyOf": [{"required": ["primitive_type"]}, {"required": ["operator"]}],
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
