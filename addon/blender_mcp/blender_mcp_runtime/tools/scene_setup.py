# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_setup_scene``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
from blender_mcp_runtime import catalogs, rna

def run_setup(args):
    bpy.ops.ed.undo_push(message="MCP Setup Scene")

    scene = bpy.context.scene
    changes = []
    warnings = []

    # 1. Camera configuration
    if "camera" in args:
        cam_info = args["camera"]
        cam_obj = scene.camera
        if not cam_obj:
            for obj in bpy.data.objects:
                if obj.type == 'CAMERA':
                    cam_obj = obj
                    break
            if not cam_obj:
                bpy.ops.object.camera_add()
                cam_obj = bpy.context.active_object
            scene.camera = cam_obj

        if "location" in cam_info:
            cam_obj.location = cam_info["location"]
            changes.append(f"camera location={cam_info['location']}")

        if "focal_length" in cam_info and cam_obj.data:
            cam_obj.data.lens = float(cam_info["focal_length"])
            changes.append(f"camera focal_length={cam_info['focal_length']}")

        if "look_at" in cam_info:
            target = cam_info["look_at"]
            target_pos = None
            if isinstance(target, str):
                target_obj = bpy.data.objects.get(target)
                if target_obj:
                    target_pos = target_obj.location
            elif isinstance(target, (list, tuple)) and len(target) == 3:
                target_pos = target

            if target_pos is not None:
                import mathutils
                loc = cam_obj.location
                direction = mathutils.Vector(target_pos) - mathutils.Vector(loc)
                rot_quat = direction.to_track_quat('-Z', 'Y')
                cam_obj.rotation_euler = rot_quat.to_euler()
                changes.append(f"camera look_at={target}")

    # 2. Light configuration
    if "light" in args:
        light_info = args["light"]
        l_name = light_info.get("name", "KeyLight")
        l_obj = bpy.data.objects.get(l_name)
        l_type = light_info.get("type", "POINT").upper()

        if not l_obj:
            bpy.ops.object.light_add(type=l_type)
            l_obj = bpy.context.active_object
            l_obj.name = l_name
            changes.append(f"created light '{l_name}'")
        else:
            if l_obj.data:
                l_obj.data.type = l_type

        if "location" in light_info:
            l_obj.location = light_info["location"]
            changes.append(f"light location={light_info['location']}")

        if l_obj.data:
            if "energy" in light_info:
                l_obj.data.energy = float(light_info["energy"])
                changes.append(f"light energy={light_info['energy']}")
            if "color" in light_info:
                c = light_info["color"]
                l_obj.data.color = c[:3]
                changes.append(f"light color={c}")

    # 3. Render engine (validated against the live engine enum)
    if "render_engine" in args:
        requested = str(args["render_engine"]).upper()
        valid_engines = {item["identifier"] for item in catalogs.render_engines()["engines"]}

        # Semantic aliases across Blender versions; never a hardcoded enum.
        if requested in ("EEVEE", "EEVEE_NEXT", "BLENDER_EEVEE_NEXT") and "BLENDER_EEVEE" in valid_engines:
            engine = "BLENDER_EEVEE"
        elif requested == "WORKBENCH":
            engine = "BLENDER_WORKBENCH"
        else:
            engine = requested

        if engine not in valid_engines:
            return {
                "status": "error",
                "message": f"Render engine '{requested}' is not available in this session. "
                           f"Valid engines: {sorted(valid_engines)}. "
                           "Enable the Cycles add-on for 'CYCLES'."
            }
        scene.render.engine = engine
        changes.append(f"render_engine={scene.render.engine}")

    # 4. Resolution
    if "resolution" in args:
        res = args["resolution"]
        if len(res) == 2:
            scene.render.resolution_x = int(res[0])
            scene.render.resolution_y = int(res[1])
            changes.append(f"resolution={res[0]}x{res[1]}")

    # 5. Samples: discover the active engine's sample property via RNA.
    if "samples" in args:
        samples = int(args["samples"])
        candidates = []
        if scene.render.engine == "CYCLES" and hasattr(scene, "cycles"):
            candidates.append(scene.cycles)
        if hasattr(scene, "eevee"):
            candidates.append(scene.eevee)
        candidates.append(scene.render)

        applied = False
        for target in candidates:
            for key in ("samples", "taa_render_samples"):
                if rna.find_property(target, key)[0] is not None:
                    result = rna.apply_properties(target, {key: samples})
                    if result.get("applied"):
                        changes.append(f"samples={samples} ({key})")
                        applied = True
                        break
            if applied:
                break
        if not applied:
            warnings.append(f"No sample property found for engine '{scene.render.engine}'")

    # 6. World background color (socket found by RNA name, not by index).
    if "world_color" in args and scene.world:
        world = scene.world
        if getattr(world, "node_tree", None) is None:
            world.use_nodes = True
        bg_node = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg_node is None:
            bg_node = world.node_tree.nodes.new("ShaderNodeBackground")
        color_socket = rna.find_socket(bg_node, "Color")
        if color_socket is not None:
            try:
                rna.set_socket_value(color_socket, args["world_color"])
                changes.append(f"world_color={args['world_color']}")
            except Exception as ex:
                warnings.append(f"Could not set world color: {ex}")
        else:
            warnings.append("World background node has no 'Color' socket")

    return {
        "status": "ok",
        "message": "Scene setup updated: " + ", ".join(changes),
        "warnings": warnings,
        "active_camera": scene.camera.name if scene.camera else None,
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y]
    }

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_setup_scene", run_setup)
