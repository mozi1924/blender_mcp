use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn transform_object(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy
import math

def run_transform(args):
    name = args.get("name")
    if not name:
        return {"status": "error", "message": "Argument 'name' is required"}

    obj = bpy.data.objects.get(name)
    if not obj:
        return {"status": "error", "message": f"Object '{name}' not found"}

    bpy.ops.ed.undo_push(message="MCP Transform Object")

    mode = args.get("mode", "absolute").lower()
    
    if "location" in args:
        loc = args["location"]
        if mode == "relative":
            obj.location[0] += loc[0]
            obj.location[1] += loc[1]
            obj.location[2] += loc[2]
        else:
            obj.location = loc

    if "rotation" in args:
        rot_deg = args["rotation"]
        rot_rad = [math.radians(a) for a in rot_deg]
        if mode == "relative":
            obj.rotation_euler[0] += rot_rad[0]
            obj.rotation_euler[1] += rot_rad[1]
            obj.rotation_euler[2] += rot_rad[2]
        else:
            obj.rotation_euler = rot_rad

    if "scale" in args:
        s = args["scale"]
        if mode == "relative":
            obj.scale[0] *= s[0]
            obj.scale[1] *= s[1]
            obj.scale[2] *= s[2]
        else:
            obj.scale = s

    if args.get("apply_transform", False):
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    rot_deg_out = [round(math.degrees(a), 2) for a in obj.rotation_euler]

    return {
        "status": "ok",
        "name": obj.name,
        "location": [round(v, 4) for v in obj.location],
        "rotation_euler_deg": rot_deg_out,
        "scale": [round(v, 4) for v in obj.scale],
        "dimensions": [round(v, 4) for v in obj.dimensions]
    }
"#;

    match call_python_tool(py, code, "run_transform", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Transform failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during transform: {}", e)),
    }
}
