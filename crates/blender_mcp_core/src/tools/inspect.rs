// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

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
import math

def run_inspect(args):
    target = args.get("target", "scene").lower().strip()

    # 1. Target: scene
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
                elif obj.type == 'CAMERA' and obj.data:
                    obj_info["lens"] = round(obj.data.lens, 1)
                elif obj.type == 'LIGHT' and obj.data:
                    obj_info["energy"] = round(obj.data.energy, 1)
                    obj_info["light_type"] = obj.data.type
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
            "active_camera": scene.camera.name if scene.camera else None,
            "world": scene.world.name if scene.world else None,
            "active_object": active_obj.name if active_obj else None,
            "selected_objects": selected_objs,
            "total_objects_in_scene": len(scene.objects),
            "frame_current": scene.frame_current,
            "frame_range": [scene.frame_start, scene.frame_end],
            "fps": scene.render.fps,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "resolution_percentage": scene.render.resolution_percentage,
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "units": {
                "system": scene.unit_settings.system,
                "scale_length": scene.unit_settings.scale_length,
                "length_unit": scene.unit_settings.length_unit
            },
            "hierarchy": dump_collection(root_col, 1)
        }

    # 2. Target: object
    elif target == "object":
        name = args.get("name")
        if not name:
            return {"status": "error", "message": "Argument 'name' is required when target is 'object'"}

        obj = bpy.data.objects.get(name)
        if not obj:
            return {"status": "error", "message": f"Object '{name}' not found"}

        if obj.rotation_mode == 'QUATERNION':
            rot_deg = [round(math.degrees(a), 2) for a in obj.rotation_quaternion.to_euler()]
        elif obj.rotation_mode == 'AXIS_ANGLE':
            import mathutils
            cur_q = mathutils.Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
            rot_deg = [round(math.degrees(a), 2) for a in cur_q.to_euler()]
        else:
            rot_deg = [round(math.degrees(a), 2) for a in obj.rotation_euler]

        # Material slots
        materials = []
        for idx, slot in enumerate(obj.material_slots):
            materials.append({
                "slot_index": idx,
                "material_name": slot.material.name if slot.material else None,
                "link": slot.link
            })

        # Adaptive modifier inspection (introspecting all active modifiers without hardcoded limits)
        base_props = set(p.identifier for p in bpy.types.Modifier.bl_rna.properties)
        modifiers = []
        for mod in obj.modifiers:
            mod_data = {
                "name": mod.name,
                "type": mod.type,
                "show_viewport": mod.show_viewport,
                "show_render": mod.show_render,
                "properties": {}
            }
            for prop in mod.bl_rna.properties:
                if prop.identifier in base_props or prop.is_readonly:
                    continue
                try:
                    val = getattr(mod, prop.identifier)
                    if prop.type == 'POINTER':
                        mod_data["properties"][prop.identifier] = val.name if val else None
                    elif isinstance(val, (set, frozenset)):
                        mod_data["properties"][prop.identifier] = list(val)
                    elif prop.type in ('INT', 'FLOAT', 'BOOLEAN', 'STRING', 'ENUM'):
                        mod_data["properties"][prop.identifier] = round(val, 4) if isinstance(val, float) else val
                    elif prop.is_array:
                        mod_data["properties"][prop.identifier] = [round(x, 4) if isinstance(x, float) else x for x in val]
                except Exception:
                    pass
            modifiers.append(mod_data)

        constraints = [{"name": c.name, "type": c.type, "influence": round(c.influence, 3)} for c in obj.constraints]

        info = {
            "status": "ok",
            "name": obj.name,
            "type": obj.type,
            "rotation_mode": obj.rotation_mode,
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
            "hide_render": obj.hide_render,
            "users_collection": [c.name for c in obj.users_collection]
        }

        # Type-specific deep details
        if obj.type == 'MESH' and obj.data:
            mesh = obj.data
            info["mesh_stats"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "faces": len(mesh.polygons),
                "vertex_groups": [vg.name for vg in obj.vertex_groups],
                "uv_layers": [uv.name for uv in mesh.uv_layers] if hasattr(mesh, "uv_layers") else [],
                "color_attributes": [ca.name for ca in mesh.color_attributes] if hasattr(mesh, "color_attributes") else [],
                "has_shape_keys": bool(mesh.shape_keys)
            }
        elif obj.type == 'CAMERA' and obj.data:
            cam = obj.data
            dof_data = None
            if hasattr(cam, "dof"):
                dof_data = {
                    "enabled": cam.dof.use_dof,
                    "focus_object": cam.dof.focus_object.name if cam.dof.focus_object else None,
                    "focus_distance": round(cam.dof.focus_distance, 3),
                    "aperture_fstop": cam.dof.aperture_fstop
                }
            info["camera_stats"] = {
                "camera_type": cam.type,
                "lens": round(cam.lens, 2),
                "clip_start": round(cam.clip_start, 3),
                "clip_end": round(cam.clip_end, 3),
                "sensor": [cam.sensor_width, cam.sensor_height],
                "dof": dof_data
            }
        elif obj.type == 'LIGHT' and obj.data:
            l = obj.data
            light_stats = {
                "light_type": l.type,
                "energy": round(l.energy, 2),
                "color": [round(c, 4) for c in l.color],
                "shadow_soft_size": getattr(l, "shadow_soft_size", None)
            }
            if l.type == 'SPOT':
                light_stats["spot_size_deg"] = round(math.degrees(l.spot_size), 2)
                light_stats["spot_blend"] = round(l.spot_blend, 3)
            elif l.type == 'AREA':
                light_stats["shape"] = getattr(l, "shape", None)
                light_stats["size"] = round(l.size, 3)
                light_stats["size_y"] = round(getattr(l, "size_y", l.size), 3)
            info["light_stats"] = light_stats
        elif obj.type in ('CURVE', 'FONT') and obj.data:
            c_data = obj.data
            info["curve_stats"] = {
                "splines_count": len(c_data.splines) if hasattr(c_data, "splines") else 0,
                "dimensions": getattr(c_data, "dimensions", None),
                "extrude": getattr(c_data, "extrude", 0.0),
                "bevel_depth": getattr(c_data, "bevel_depth", 0.0)
            }
        elif obj.type == 'CURVES' and obj.data:
            curves_data = obj.data
            info["curves_stats"] = {
                "curves_count": len(curves_data.curves) if hasattr(curves_data, "curves") else 0,
                "points_count": len(curves_data.points) if hasattr(curves_data, "points") else 0
            }
        elif obj.type == 'GREASE_PENCIL' and obj.data:
            gp_data = obj.data
            info["grease_pencil_stats"] = {
                "layers_count": len(gp_data.layers) if hasattr(gp_data, "layers") else 0,
                "layers": [layer.name for layer in gp_data.layers] if hasattr(gp_data, "layers") else []
            }
        elif obj.type == 'ARMATURE' and obj.data:
            arm = obj.data
            info["armature_stats"] = {
                "bones_count": len(arm.bones),
                "bones": [b.name for b in arm.bones[:30]]
            }
        elif obj.type == 'EMPTY':
            info["empty_stats"] = {
                "display_type": obj.empty_display_type,
                "display_size": round(obj.empty_display_size, 3)
            }

        # Animation & Slotted Actions (Blender 5.2 layered action standard)
        if obj.animation_data:
            action = obj.animation_data.action
            action_data = None
            if action:
                slots = []
                if hasattr(action, "slots"):
                    for s in action.slots:
                        slots.append({
                            "identifier": s.identifier,
                            "target_id_type": s.target_id_type,
                            "name": getattr(s, "name_display", s.identifier)
                        })
                action_data = {
                    "name": action.name,
                    "frame_range": [round(action.frame_range[0], 2), round(action.frame_range[1], 2)],
                    "is_layered": getattr(action, "is_action_layered", True),
                    "slots": slots
                }
            info["animation"] = {
                "action": action_data,
                "drivers_count": len(obj.animation_data.drivers) if obj.animation_data.drivers else 0,
                "nla_tracks_count": len(obj.animation_data.nla_tracks) if obj.animation_data.nla_tracks else 0
            }

        # Custom properties
        custom_props = {k: str(obj[k]) for k in obj.keys() if k != "_RNA_UI"}
        if custom_props:
            info["custom_properties"] = custom_props

        return info

    # 3. Target: file
    elif target == "file":
        missing_files = []
        for img in bpy.data.images:
            if img.source == 'FILE' and img.filepath:
                import os
                path = bpy.path.abspath(img.filepath)
                if not os.path.exists(path):
                    missing_files.append({"type": "IMAGE", "name": img.name, "path": img.filepath})

        libraries = [lib.filepath for lib in bpy.data.libraries]

        build_hash = bpy.app.build_hash
        if isinstance(build_hash, bytes):
            build_hash = build_hash.decode("utf-8")

        return {
            "status": "ok",
            "filepath": bpy.data.filepath,
            "is_saved": bpy.data.is_saved,
            "is_dirty": bpy.data.is_dirty,
            "version": list(bpy.app.version),
            "version_string": bpy.app.version_string,
            "build_hash": str(build_hash),
            "linked_libraries": libraries,
            "missing_files": missing_files,
        }

    # 4. Target: datablocks
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
            "curves": len(bpy.data.curves) if hasattr(bpy.data, "curves") else 0,
            "hair_curves": len(bpy.data.hair_curves) if hasattr(bpy.data, "hair_curves") else 0,
            "grease_pencils": len(bpy.data.grease_pencils) if hasattr(bpy.data, "grease_pencils") else 0,
            "armatures": len(bpy.data.armatures) if hasattr(bpy.data, "armatures") else 0,
            "volumes": len(bpy.data.volumes) if hasattr(bpy.data, "volumes") else 0,
            "pointclouds": len(bpy.data.pointclouds) if hasattr(bpy.data, "pointclouds") else 0,
            "fonts": len(bpy.data.fonts) if hasattr(bpy.data, "fonts") else 0,
            "brushes": len(bpy.data.brushes) if hasattr(bpy.data, "brushes") else 0,
            "workspaces": len(bpy.data.workspaces) if hasattr(bpy.data, "workspaces") else 0,
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
