use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn setup_scene(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def run_setup(args):
    bpy.ops.ed.undo_push(message="MCP Setup Scene")

    scene = bpy.context.scene
    changes = []

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

    # 3. Render engine
    if "render_engine" in args:
        engine = args["render_engine"].upper()
        if engine in ("EEVEE", "BLENDER_EEVEE", "EEVEE_NEXT", "BLENDER_EEVEE_NEXT"):
            scene.render.engine = 'BLENDER_EEVEE_NEXT' if hasattr(bpy.types, "RenderSettings") else 'BLENDER_EEVEE'
        elif engine in ("CYCLES",):
            scene.render.engine = 'CYCLES'
        elif engine in ("WORKBENCH", "BLENDER_WORKBENCH"):
            scene.render.engine = 'BLENDER_WORKBENCH'
        changes.append(f"render_engine={scene.render.engine}")

    # 4. Resolution
    if "resolution" in args:
        res = args["resolution"]
        if len(res) == 2:
            scene.render.resolution_x = int(res[0])
            scene.render.resolution_y = int(res[1])
            changes.append(f"resolution={res[0]}x{res[1]}")

    # 5. Samples
    if "samples" in args:
        samples = int(args["samples"])
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = samples
        elif hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "taa_render_samples"):
                scene.eevee.taa_render_samples = samples
        changes.append(f"samples={samples}")

    # 6. World background color
    if "world_color" in args and scene.world and scene.world.use_nodes:
        bg_node = None
        for node in scene.world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                bg_node = node
                break
        if bg_node:
            c = args["world_color"]
            if len(c) == 3:
                c = [c[0], c[1], c[2], 1.0]
            bg_node.inputs['Color'].default_value = c
            changes.append(f"world_color={c}")

    return {
        "status": "ok",
        "message": "Scene setup updated: " + ", ".join(changes),
        "active_camera": scene.camera.name if scene.camera else None,
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y]
    }
"#;

    match call_python_tool(py, code, "run_setup", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Scene setup failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during scene setup: {}", e)),
    }
}
