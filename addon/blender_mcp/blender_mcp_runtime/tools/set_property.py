# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""``blender_set``: generic RNA property writes and transform conveniences.

This is the consolidation tool that replaces the former ``transform_object``,
``manage_material`` configuration and ``setup_scene`` property writes.  It
resolves a datablock/path expression and applies any RNA property through the
same coercion layer used by every other tool.
"""

from __future__ import annotations

import bpy
import math
import mathutils

from .. import registry, rna

_ORIGIN_MAP = {
    "GEOMETRY": "ORIGIN_GEOMETRY",
    "ORIGIN_GEOMETRY": "ORIGIN_GEOMETRY",
    "GEOMETRY_ORIGIN": "ORIGIN_GEOMETRY",
    "CURSOR": "ORIGIN_CURSOR",
    "ORIGIN_CURSOR": "ORIGIN_CURSOR",
    "CENTER_OF_MASS": "ORIGIN_CENTER_OF_MASS",
    "ORIGIN_CENTER_OF_MASS": "ORIGIN_CENTER_OF_MASS",
    "CENTER_OF_VOLUME": "ORIGIN_CENTER_OF_VOLUME",
    "ORIGIN_CENTER_OF_VOLUME": "ORIGIN_CENTER_OF_VOLUME",
}


def _set_origin(obj, origin_type):
    origin_type = str(origin_type).upper().strip()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if origin_type == "BOTTOM":
        bbox_world = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
        min_z = min(value.z for value in bbox_world)
        center_x = sum(value.x for value in bbox_world) / 8.0
        center_y = sum(value.y for value in bbox_world) / 8.0
        old_cursor = bpy.context.scene.cursor.location.copy()
        bpy.context.scene.cursor.location = mathutils.Vector((center_x, center_y, min_z))
        try:
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        finally:
            bpy.context.scene.cursor.location = old_cursor
        return "BOTTOM"

    target = _ORIGIN_MAP.get(origin_type)
    if target is None:
        valid = sorted(set(_ORIGIN_MAP.values()) | {"BOTTOM"})
        raise ValueError(f"Unknown origin_to '{origin_type}'. Valid: {valid}")
    bpy.ops.object.origin_set(type=target, center="BOUNDS" if target == "ORIGIN_GEOMETRY" else "MEDIAN")
    return origin_type


def _look_at(obj, value):
    target_pos = None
    if isinstance(value, str):
        target = bpy.data.objects.get(value)
        if target is not None:
            target_pos = target.matrix_world.translation
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        target_pos = mathutils.Vector(value)
    if target_pos is None:
        raise ValueError("look_at expects [x, y, z] or an object name")

    direction = mathutils.Vector(target_pos) - obj.matrix_world.translation
    if direction.length == 0.0:
        raise ValueError("look_at target is at the same position as the object")
    rotation = direction.to_track_quat("-Z", "Y")
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = rotation
    elif obj.rotation_mode == "AXIS_ANGLE":
        axis, angle = rotation.to_axis_angle()
        obj.rotation_axis_angle = [angle, axis.x, axis.y, axis.z]
    else:
        obj.rotation_euler = rotation.to_euler()
    return list(value) if not isinstance(value, str) else value


def _relative_value(prop, identifier, current, value):
    if prop.type not in ("INT", "FLOAT"):
        raise ValueError(f"mode='relative' only supports numeric properties, not '{prop.type}'")
    if "quaternion" in identifier.lower() or "axis_angle" in identifier.lower():
        raise ValueError(
            f"Relative rotation for '{identifier}' is not supported; use an absolute value "
            "or blender_run_operator('transform.rotate')."
        )
    if getattr(prop, "is_array", False):
        current = list(current)
        if "scale" in identifier.lower():
            return [a * b for a, b in zip(current, value)]
        return [a + b for a, b in zip(current, value)]
    if "scale" in identifier.lower():
        return current * value
    return current + value


def _append(path, root, value):
    parent, leaf = rna.resolve_path_with_leaf(root, path)
    prop, identifier, _score = rna.find_property(parent, leaf)
    if prop is None:
        options = [item.identifier for item in parent.bl_rna.properties] if hasattr(parent, "bl_rna") else []
        raise KeyError(f"Unknown property '{leaf}'. Did you mean: {rna.suggest(leaf, options)}")
    if prop.type != "COLLECTION":
        raise ValueError(f"mode='append' requires a collection property, '{identifier}' is {prop.type}")

    collection = getattr(parent, identifier)
    values = rna.coerce_value(prop, value)
    appended = []
    for item in values:
        if hasattr(collection, "append"):
            collection.append(item)
        elif hasattr(collection, "link"):
            collection.link(item)
        else:
            raise ValueError(f"Collection '{identifier}' does not support append/link")
        appended.append(getattr(item, "name", str(item)))
    return appended


def run(args):
    target = args.get("target")
    if not target:
        raise ValueError("Argument 'target' is required")

    root = rna.resolve_target(target, create=bool(args.get("create", False)))
    path = args.get("path") or ""
    mode = str(args.get("mode", "absolute")).lower()
    undo = bool(args.get("undo", True))

    if args.get("origin_to") is not None:
        if not isinstance(root, bpy.types.Object):
            raise ValueError("origin_to requires an object target")
        if undo:
            bpy.ops.ed.undo_push(message="MCP Set Origin")
        _set_origin(root, args["origin_to"])

    if (
        args.get("origin_to") is not None
        and not path
        and "properties" not in args
        and "value" not in args
        and mode != "append"
    ):
        return {
            "status": "ok",
            "target": str(target),
            "origin_to": args["origin_to"],
        }

    if path in ("rotation", "rotation_deg"):
        if not isinstance(root, bpy.types.Object):
            raise ValueError("rotation path requires an object target")
        value = args.get("value")
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError("rotation expects a 3-value degree array")
        radians = [math.radians(float(item)) for item in value]
        if undo:
            bpy.ops.ed.undo_push(message="MCP Set Rotation")
        if root.rotation_mode == "QUATERNION":
            delta = mathutils.Euler(radians, "XYZ").to_quaternion()
            root.rotation_quaternion = (
                delta @ root.rotation_quaternion if mode == "relative" else delta
            )
        elif root.rotation_mode == "AXIS_ANGLE":
            delta = mathutils.Euler(radians, "XYZ").to_quaternion()
            current = mathutils.Quaternion(
                root.rotation_axis_angle[1:], root.rotation_axis_angle[0]
            )
            result = delta @ current if mode == "relative" else delta
            axis, angle = result.to_axis_angle()
            root.rotation_axis_angle = [angle, axis.x, axis.y, axis.z]
        elif mode == "relative":
            root.rotation_euler = [
                current + delta for current, delta in zip(root.rotation_euler, radians)
            ]
        else:
            root.rotation_euler = radians
        return {
            "status": "ok",
            "target": str(target),
            "path": path,
            "applied": {"rotation": rna.jsonable(root.rotation_euler if root.rotation_mode == "XYZ" else value)},
        }

    if path in ("look_at", "aim_at"):
        if not isinstance(root, bpy.types.Object):
            raise ValueError("look_at requires an object target")
        if undo:
            bpy.ops.ed.undo_push(message="MCP Look At")
        aimed = _look_at(root, args.get("value"))
        return {
            "status": "ok",
            "target": str(target),
            "path": path,
            "applied": {"look_at": aimed},
        }

    if mode == "append":
        if not path or "value" not in args:
            raise ValueError("mode='append' requires 'path' and 'value'")
        if undo:
            bpy.ops.ed.undo_push(message="MCP Append Property")
        appended = _append(path, root, args["value"])
        return {
            "status": "ok",
            "target": str(target),
            "path": path,
            "appended": appended,
        }

    properties = args.get("properties")
    if isinstance(properties, dict):
        node = rna.resolve_path(root, path) if path else root
        if undo:
            bpy.ops.ed.undo_push(message="MCP Set Property")
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
        raise ValueError("Provide 'properties' (batch), 'value' (single property), or mode='append'")
    if not path:
        raise ValueError("Argument 'path' is required when setting a single 'value'")

    parent, leaf = rna.resolve_path_with_leaf(root, path)
    prop, identifier, _score = rna.find_property(parent, leaf)
    if prop is None:
        options = [item.identifier for item in parent.bl_rna.properties] if hasattr(parent, "bl_rna") else []
        raise KeyError(f"Unknown property '{leaf}'. Did you mean: {rna.suggest(leaf, options)}")

    value = args["value"]
    if (
        args.get("unit") == "degrees"
        and prop.type == "FLOAT"
        and getattr(prop, "subtype", "") == "EULER"
    ):
        if not isinstance(value, (list, tuple)):
            raise ValueError("'degrees' unit expects a 3-value rotation array")
        value = [math.radians(float(item)) for item in value]

    if mode == "relative":
        value = _relative_value(prop, identifier, getattr(parent, identifier), value)

    if undo:
        bpy.ops.ed.undo_push(message="MCP Set Property")

    result = rna.apply_properties(parent, {identifier: value})
    ok = not result.get("errors") and not result.get("unknown")
    return {
        "status": "ok" if ok else "error",
        "target": str(target),
        "path": path,
        "property": identifier,
        "mode": mode,
        **result,
    }


registry.register(
    name="blender_set",
    handler=run,
    description=(
        "Set any Blender RNA property through a uniform path resolver, or use transform "
        "conveniences. Examples: target='object:RustCube', path='location', value=[1,2,3]; "
        "target='object:Camera', path='look_at', value='RustCube'; "
        "target='object:RustCube', path='rotation_euler', value=[90,0,0], unit='degrees'; "
        "target='object:RustCube', path='location', value=[1,0,0], mode='relative'; "
        "target='object:RustCube', path='data.materials', value='MetallicBlue', mode='append'; "
        "target='material:MetallicBlue', create=true, properties={'use_nodes': True}; "
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
                    "Relative RNA path. Examples: 'location', 'rotation' (degrees, adapts to rotation_mode), 'look_at', "
                    "'modifiers[Subsurf].levels', "
                    "'node_tree.nodes[Principled BSDF].inputs[Base Color].default_value', "
                    "'render.engine', 'data.materials' (with mode='append')."
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
            "mode": {
                "type": "string",
                "enum": ["absolute", "relative", "append"],
                "default": "absolute",
                "description": (
                    "absolute: set value; relative: add numeric values (scale multiplies); "
                    "append: append a datablock to a collection property (e.g. data.materials)."
                ),
            },
            "create": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Create the target datablock if missing (material, light, camera, world, "
                    "collection, mesh, curve, scene, ...)."
                ),
            },
            "origin_to": {
                "type": "string",
                "description": (
                    "Set object origin before applying properties: GEOMETRY, BOTTOM, CURSOR, "
                    "CENTER_OF_MASS, CENTER_OF_VOLUME (or raw object.origin_set identifiers)."
                ),
            },
            "undo": {
                "type": "boolean",
                "default": True,
                "description": "Push an undo step before applying.",
            },
        },
        "anyOf": [
            {"required": ["properties"]},
            {"required": ["value"]},
            {"required": ["origin_to"]},
        ],
    },
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
