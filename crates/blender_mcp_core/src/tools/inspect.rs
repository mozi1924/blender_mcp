use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn inspect(py: Python<'_>, mut args: serde_json::Value) -> ToolCallResponse {
    let target = args
        .get("target")
        .and_then(|v| v.as_str())
        .unwrap_or("scene")
        .to_string();

    if let Some(obj) = args.as_object_mut() {
        obj.insert("target".to_string(), serde_json::Value::String(target));
    }

    let code = r#"
import bpy

def run_inspect(args):
    target = args.get("target", "scene")
    if target == "scene":
        scene = bpy.context.scene
        active_obj = bpy.context.active_object
        selected_objs = [obj.name for obj in bpy.context.selected_objects]

        max_depth = args.get("depth", 3)
        col_filter = args.get("collection")
        type_filter = args.get("object_type")

        def dump_collection(col, current_depth):
            if current_depth > max_depth:
                return {"name": col.name, "truncated": True}

            objs = []
            for obj in col.objects:
                if type_filter and obj.type != type_filter:
                    continue
                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    "location": [round(v, 4) for v in obj.location],
                    "hide_viewport": obj.hide_get(),
                    "hide_render": obj.hide_render,
                }
                if obj.type == 'MESH' and obj.data:
                    obj_info["vertices"] = len(obj.data.vertices)
                    obj_info["polygons"] = len(obj.data.polygons)
                objs.append(obj_info)

            children = [dump_collection(child, current_depth + 1) for child in col.children]
            return {
                "name": col.name,
                "objects_count": len(objs),
                "objects": objs,
                "children": children,
            }

        root_col = scene.collection
        if col_filter and col_filter in bpy.data.collections:
            root_col = bpy.data.collections[col_filter]

        return {
            "status": "ok",
            "scene": scene.name,
            "render_engine": scene.render.engine,
            "active_object": active_obj.name if active_obj else None,
            "selected_objects": selected_objs,
            "total_objects_in_scene": len(scene.objects),
            "hierarchy": dump_collection(root_col, 1)
        }

    elif target == "object":
        name = args.get("name")
        if not name:
            return {"status": "error", "message": "Argument 'name' is required when target is 'object'"}
        
        obj = bpy.data.objects.get(name)
        if not obj:
            return {"status": "error", "message": f"Object '{name}' not found"}

        import math
        rot_deg = [round(math.degrees(a), 2) for a in obj.rotation_euler]

        materials = []
        for slot in obj.material_slots:
            materials.append(slot.material.name if slot.material else None)

        modifiers = []
        for mod in obj.modifiers:
            mod_data = {
                "name": mod.name,
                "type": mod.type,
                "show_viewport": mod.show_viewport,
                "show_render": mod.show_render
            }
            if mod.type == 'SUBSURF':
                mod_data["levels"] = mod.levels
                mod_data["render_levels"] = mod.render_levels
            elif mod.type == 'BEVEL':
                mod_data["width"] = round(mod.width, 4)
                mod_data["segments"] = mod.segments
            elif mod.type == 'BOOLEAN':
                mod_data["operation"] = mod.operation
                mod_data["object"] = mod.object.name if mod.object else None
            elif mod.type == 'MIRROR':
                mod_data["use_axis"] = [mod.use_axis[0], mod.use_axis[1], mod.use_axis[2]]
            elif mod.type == 'SOLIDIFY':
                mod_data["thickness"] = round(mod.thickness, 4)
            modifiers.append(mod_data)

        constraints = [{"name": c.name, "type": c.type} for c in obj.constraints]

        info = {
            "status": "ok",
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 4) for v in obj.location],
            "rotation_euler_deg": rot_deg,
            "scale": [round(v, 4) for v in obj.scale],
            "dimensions": [round(v, 4) for v in obj.dimensions],
            "materials": materials,
            "modifiers": modifiers,
            "constraints": constraints,
            "parent": obj.parent.name if obj.parent else None,
            "children": [c.name for c in obj.children],
            "visible": not obj.hide_get(),
        }

        if obj.type == 'MESH' and obj.data:
            info["mesh_stats"] = {
                "vertices": len(obj.data.vertices),
                "edges": len(obj.data.edges),
                "faces": len(obj.data.polygons),
            }
        return info

    elif target == "file":
        missing_files = []
        for img in bpy.data.images:
            if img.source == 'FILE' and img.filepath:
                import os
                path = bpy.path.abspath(img.filepath)
                if not os.path.exists(path):
                    missing_files.append({"type": "IMAGE", "name": img.name, "path": img.filepath})

        libraries = [lib.filepath for lib in bpy.data.libraries]

        return {
            "status": "ok",
            "filepath": bpy.data.filepath,
            "is_saved": bpy.data.is_saved,
            "is_dirty": bpy.data.is_dirty,
            "version": list(bpy.app.version),
            "linked_libraries": libraries,
            "missing_files": missing_files,
        }

    elif target == "datablocks":
        return {
            "status": "ok",
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "textures": len(bpy.data.textures),
            "images": len(bpy.data.images),
            "cameras": len(bpy.data.cameras),
            "lights": len(bpy.data.lights),
            "collections": len(bpy.data.collections),
            "actions": len(bpy.data.actions),
            "node_groups": len(bpy.data.node_groups),
            "scenes": len(bpy.data.scenes),
            "worlds": len(bpy.data.worlds),
        }
    else:
        return {"status": "error", "message": f"Unknown target '{target}'. Allowed: scene, object, file, datablocks"}
"#;

    match call_python_tool(py, code, "run_inspect", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Inspect failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during inspect: {}", e)),
    }
}
