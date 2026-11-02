use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn create_primitive(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy
import math

def run_create(args):
    bpy.ops.ed.undo_push(message="MCP Create Primitive")

    ptype = args.get("primitive_type", "cube").lower()
    name = args.get("name")
    loc = args.get("location", [0.0, 0.0, 0.0])
    rot_deg = args.get("rotation", [0.0, 0.0, 0.0])
    rot = [math.radians(a) for a in rot_deg]
    scale = args.get("scale", [1.0, 1.0, 1.0])
    target_col_name = args.get("collection")
    extra = args.get("extra", {})

    # Execute primitive creation operator
    if ptype in ("cube", "box"):
        size = extra.get("size", 2.0)
        bpy.ops.mesh.primitive_cube_add(size=size, location=loc, rotation=rot, scale=scale)
    elif ptype in ("sphere", "uv_sphere"):
        radius = extra.get("radius", 1.0)
        segments = extra.get("segments", 32)
        ring_count = extra.get("ring_count", 16)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=segments, ring_count=ring_count, location=loc, rotation=rot, scale=scale)
    elif ptype in ("ico_sphere", "icosphere"):
        radius = extra.get("radius", 1.0)
        subdivisions = extra.get("subdivisions", 2)
        bpy.ops.mesh.primitive_ico_sphere_add(radius=radius, subdivisions=subdivisions, location=loc, rotation=rot, scale=scale)
    elif ptype in ("cylinder",):
        radius = extra.get("radius", 1.0)
        depth = extra.get("depth", 2.0)
        vertices = extra.get("vertices", 32)
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=vertices, location=loc, rotation=rot, scale=scale)
    elif ptype in ("cone",):
        radius1 = extra.get("radius1", 1.0)
        depth = extra.get("depth", 2.0)
        bpy.ops.mesh.primitive_cone_add(radius1=radius1, depth=depth, location=loc, rotation=rot, scale=scale)
    elif ptype in ("torus",):
        major_radius = extra.get("major_radius", 1.0)
        minor_radius = extra.get("minor_radius", 0.25)
        bpy.ops.mesh.primitive_torus_add(major_radius=major_radius, minor_radius=minor_radius, location=loc, rotation=rot)
        bpy.context.active_object.scale = scale
    elif ptype in ("plane",):
        size = extra.get("size", 2.0)
        bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot, scale=scale)
    elif ptype in ("circle",):
        radius = extra.get("radius", 1.0)
        bpy.ops.mesh.primitive_circle_add(radius=radius, location=loc, rotation=rot, scale=scale)
    elif ptype in ("text",):
        bpy.ops.object.text_add(location=loc, rotation=rot, scale=scale)
        body = extra.get("text")
        if body and bpy.context.active_object and bpy.context.active_object.data:
            bpy.context.active_object.data.body = str(body)
    elif ptype in ("curve_bezier", "bezier"):
        bpy.ops.curve.primitive_bezier_curve_add(location=loc, rotation=rot, scale=scale)
    elif ptype in ("curve_circle",):
        bpy.ops.curve.primitive_bezier_circle_add(location=loc, rotation=rot, scale=scale)
    elif ptype in ("empty",):
        empty_type = extra.get("empty_draw_type", "PLAIN_AXES")
        bpy.ops.object.empty_add(type=empty_type, location=loc, rotation=rot, scale=scale)
    elif ptype in ("camera",):
        bpy.ops.object.camera_add(location=loc, rotation=rot)
        bpy.context.active_object.scale = scale
    elif ptype in ("light",):
        light_type = extra.get("light_type", "POINT").upper()
        bpy.ops.object.light_add(type=light_type, location=loc, rotation=rot)
        if "energy" in extra and bpy.context.active_object.data:
            bpy.context.active_object.data.energy = float(extra["energy"])
        if "color" in extra and bpy.context.active_object.data:
            bpy.context.active_object.data.color = extra["color"][:3]
    else:
        return {"status": "error", "message": f"Unsupported primitive_type '{ptype}'"}

    obj = bpy.context.active_object
    if not obj:
        return {"status": "error", "message": "Failed to create primitive (no active object)"}

    # Rename if specified
    if name:
        obj.name = name

    # Move to target collection if specified
    if target_col_name:
        target_col = bpy.data.collections.get(target_col_name)
        if not target_col:
            target_col = bpy.data.collections.new(target_col_name)
            bpy.context.scene.collection.children.link(target_col)
        # Link to target collection and unlink from current
        if obj.name not in target_col.objects:
            target_col.objects.link(obj)
            for c in obj.users_collection:
                if c != target_col:
                    c.objects.unlink(obj)

    return {
        "status": "ok",
        "created_object": {
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 4) for v in obj.location],
            "rotation_euler_deg": rot_deg,
            "scale": [round(v, 4) for v in obj.scale],
            "collection": obj.users_collection[0].name if obj.users_collection else None
        }
    }
"#;

    match call_python_tool(py, code, "run_create", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Creation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during primitive creation: {}", e)),
    }
}
