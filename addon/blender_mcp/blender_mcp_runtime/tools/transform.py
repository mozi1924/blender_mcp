# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_transform_object``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
import math
import mathutils

def run_transform(args):
    name = args.get("name")
    if not name:
        return {"status": "error", "message": "Argument 'name' is required"}

    obj = bpy.data.objects.get(name)
    if not obj:
        return {"status": "error", "message": f"Object '{name}' not found"}

    bpy.ops.ed.undo_push(message="MCP Transform Object")

    mode = args.get("mode", "absolute").lower()

    # 1. Location
    if "location" in args:
        loc = args["location"]
        if mode == "relative":
            obj.location[0] += loc[0]
            obj.location[1] += loc[1]
            obj.location[2] += loc[2]
        else:
            obj.location = loc

    # 2. Rotation with rotation_mode adaptability (Euler, Quaternion, Axis-Angle)
    if "rotation" in args:
        rot_deg = args["rotation"]
        rot_rad = [math.radians(a) for a in rot_deg]
        
        if obj.rotation_mode == 'QUATERNION':
            delta_q = mathutils.Euler(rot_rad, 'XYZ').to_quaternion()
            if mode == "relative":
                obj.rotation_quaternion = delta_q @ obj.rotation_quaternion
            else:
                obj.rotation_quaternion = delta_q
        elif obj.rotation_mode == 'AXIS_ANGLE':
            delta_q = mathutils.Euler(rot_rad, 'XYZ').to_quaternion()
            axis, angle = delta_q.to_axis_angle()
            if mode == "relative":
                cur_q = mathutils.Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
                new_q = delta_q @ cur_q
                n_axis, n_angle = new_q.to_axis_angle()
                obj.rotation_axis_angle = [n_angle, n_axis.x, n_axis.y, n_axis.z]
            else:
                obj.rotation_axis_angle = [angle, axis.x, axis.y, axis.z]
        else:
            # Euler rotation
            if mode == "relative":
                obj.rotation_euler[0] += rot_rad[0]
                obj.rotation_euler[1] += rot_rad[1]
                obj.rotation_euler[2] += rot_rad[2]
            else:
                obj.rotation_euler = rot_rad

    # 3. Scale
    if "scale" in args:
        s = args["scale"]
        if mode == "relative":
            obj.scale[0] *= s[0]
            obj.scale[1] *= s[1]
            obj.scale[2] *= s[2]
        else:
            obj.scale = s

    # 3b. Look-at convenience (covers the camera aiming use case)
    if args.get("look_at") is not None:
        look_at = args["look_at"]
        target_pos = None
        if isinstance(look_at, str):
            target_obj = bpy.data.objects.get(look_at)
            if target_obj is not None:
                target_pos = target_obj.matrix_world.translation
        elif isinstance(look_at, (list, tuple)) and len(look_at) == 3:
            target_pos = mathutils.Vector(look_at)

        if target_pos is not None:
            direction = mathutils.Vector(target_pos) - obj.matrix_world.translation
            if direction.length > 0.0:
                rot_quat = direction.to_track_quat('-Z', 'Y')
                if obj.rotation_mode == 'QUATERNION':
                    obj.rotation_quaternion = rot_quat
                elif obj.rotation_mode == 'AXIS_ANGLE':
                    axis, angle = rot_quat.to_axis_angle()
                    obj.rotation_axis_angle = [angle, axis.x, axis.y, axis.z]
                else:
                    obj.rotation_euler = rot_quat.to_euler()

    # Ensure transforms are evaluated in dependency graph before origin/apply operations
    bpy.context.view_layer.update()

    # 4. Origin manipulation
    origin_to = args.get("origin_to")
    if origin_to:
        origin_type = str(origin_to).upper().strip()
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        if origin_type in ("GEOMETRY", "ORIGIN_GEOMETRY", "GEOMETRY_ORIGIN"):
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        elif origin_type in ("CURSOR", "ORIGIN_CURSOR"):
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        elif origin_type in ("CENTER_OF_MASS", "ORIGIN_CENTER_OF_MASS"):
            bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS')
        elif origin_type in ("CENTER_OF_VOLUME", "ORIGIN_CENTER_OF_VOLUME"):
            bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')
        elif origin_type == "BOTTOM":
            # Set origin to bottom center of bounding box
            bbox_world = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
            min_z = min(v.z for v in bbox_world)
            center_x = sum(v.x for v in bbox_world) / 8.0
            center_y = sum(v.y for v in bbox_world) / 8.0
            old_cursor = bpy.context.scene.cursor.location.copy()
            bpy.context.scene.cursor.location = mathutils.Vector((center_x, center_y, min_z))
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
            bpy.context.scene.cursor.location = old_cursor

    # 5. Fine-grained Apply Transforms
    apply_all = args.get("apply_transform", False)
    apply_loc = args.get("apply_location", False) or apply_all
    apply_rot = args.get("apply_rotation", False) or apply_all
    apply_scale = args.get("apply_scale", False) or apply_all

    if apply_loc or apply_rot or apply_scale:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.transform_apply(location=apply_loc, rotation=apply_rot, scale=apply_scale)
        except Exception as ex:
            print(f"Warning: could not apply transform: {ex}")

    # Output current rotations in degrees
    if obj.rotation_mode == 'QUATERNION':
        rot_deg_out = [round(math.degrees(a), 2) for a in obj.rotation_quaternion.to_euler()]
    elif obj.rotation_mode == 'AXIS_ANGLE':
        cur_q = mathutils.Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
        rot_deg_out = [round(math.degrees(a), 2) for a in cur_q.to_euler()]
    else:
        rot_deg_out = [round(math.degrees(a), 2) for a in obj.rotation_euler]

    return {
        "status": "ok",
        "name": obj.name,
        "rotation_mode": obj.rotation_mode,
        "location": [round(v, 4) for v in obj.location],
        "rotation_euler_deg": rot_deg_out,
        "scale": [round(v, 4) for v in obj.scale],
        "dimensions": [round(v, 4) for v in obj.dimensions]
    }

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_transform_object", run_transform)
