# SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrated handler for ``blender_capture``.

Logic is unchanged from the Rust-embedded implementation, except that shared
RNA helpers/catalogs are imported from the persistent runtime instead of being
duplicated or recompiled per call.
"""


import bpy
import os
import tempfile
import base64

def run_capture(args):
    view = args.get("view", "camera").lower()
    shading_type = args.get("shading_type")
    film_transparent = args.get("film_transparent")
    camera_name = args.get("camera")
    return_image = args.get("return_image", True)
    custom_out = args.get("output_path")
    res = args.get("resolution", [800, 600])

    scene_name = args.get("scene") or args.get("scene_name")
    if scene_name:
        scene = bpy.data.scenes.get(scene_name)
        if not scene:
            return {"status": "error", "message": f"Scene '{scene_name}' not found in bpy.data.scenes"}
    else:
        scene = bpy.context.scene

    view_layer_name = args.get("view_layer") or args.get("layer")
    if view_layer_name and hasattr(scene, "view_layers") and view_layer_name not in scene.view_layers:
        valid_layers = [vl.name for vl in scene.view_layers]
        return {"status": "error", "message": f"View layer '{view_layer_name}' not found in scene '{scene.name}'. Available: {valid_layers}"}

    orig_rx = scene.render.resolution_x
    orig_ry = scene.render.resolution_y
    orig_pct = scene.render.resolution_percentage
    orig_fp = scene.render.filepath
    orig_film = scene.render.film_transparent
    orig_cam = scene.camera

    tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()

    try:
        scene.render.resolution_x = int(res[0])
        scene.render.resolution_y = int(res[1])
        scene.render.resolution_percentage = 100
        scene.render.filepath = tmp_path

        if film_transparent is not None:
            scene.render.film_transparent = bool(film_transparent)

        if camera_name:
            cam_obj = bpy.data.objects.get(camera_name)
            if cam_obj and cam_obj.type == 'CAMERA':
                scene.camera = cam_obj

        # Perform render or viewport capture
        render_kwargs = {"write_still": True}
        if scene != bpy.context.scene:
            render_kwargs["scene"] = scene.name
        if view_layer_name:
            render_kwargs["layer"] = view_layer_name

        if bpy.app.background:
            # Background / headless mode always uses standard render engine
            with bpy.context.temp_override(scene=scene):
                bpy.ops.render.render(**render_kwargs)
        elif view == "viewport":
            # Interactive 3D viewport capture with context override
            area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None) if bpy.context.screen else None
            if area:
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                space = area.spaces.active if area.spaces else None
                orig_shading = None
                if space and hasattr(space, "shading") and shading_type:
                    orig_shading = space.shading.type
                    try:
                        space.shading.type = shading_type.upper()
                    except Exception:
                        pass
                try:
                    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region, scene=scene):
                        bpy.ops.render.opengl(write_still=True, view_context=True)
                finally:
                    if space and orig_shading:
                        space.shading.type = orig_shading
            else:
                with bpy.context.temp_override(scene=scene):
                    bpy.ops.render.opengl(write_still=True, view_context=False)
        else:
            # Standard camera render
            with bpy.context.temp_override(scene=scene):
                bpy.ops.render.render(**render_kwargs)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            return {"status": "error", "message": "Render failed to produce output image"}

        target_path = tmp_path
        if custom_out:
            import shutil
            shutil.copy2(tmp_path, custom_out)
            target_path = custom_out

        b64_data = ""
        if return_image:
            with open(tmp_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

        result = {
            "status": "ok",
            "base64": b64_data,
            "filepath": target_path,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "scene": scene.name,
            "view": view,
            "camera": scene.camera.name if scene.camera else None,
            "film_transparent": scene.render.film_transparent
        }
        if view_layer_name:
            result["view_layer"] = view_layer_name

        if b64_data:
            # MCP multi-modal content: Rust maps this directly to image blocks.
            extra_layer = f", view_layer: {view_layer_name}" if view_layer_name else ""
            result["content"] = [
                {
                    "type": "text",
                    "text": (
                        f"Blender capture rendered (scene: {scene.name}{extra_layer}, view: {view}, "
                        f"resolution: {scene.render.resolution_x}x{scene.render.resolution_y}, "
                        f"camera: {result['camera']})"
                    ),
                },
                {"type": "image", "data": b64_data, "mimeType": "image/png"},
            ]
        return result
    except Exception as ex:
        import traceback
        return {"status": "error", "message": f"Capture error: {ex}\n{traceback.format_exc()}"}
    finally:
        scene.render.resolution_x = orig_rx
        scene.render.resolution_y = orig_ry
        scene.render.resolution_percentage = orig_pct
        scene.render.filepath = orig_fp
        scene.render.film_transparent = orig_film
        scene.camera = orig_cam
        if return_image and not custom_out and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

# --- MCP registration -------------------------------------------------------
from ..registry import register
from . import schemas

schemas.register_tool(register, "blender_capture", run_capture)
