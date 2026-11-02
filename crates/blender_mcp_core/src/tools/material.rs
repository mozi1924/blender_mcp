use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_material(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def hex_to_rgba(hex_str):
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0
        return [r, g, b, 1.0]
    elif len(hex_str) == 8:
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0
        a = int(hex_str[6:8], 16) / 255.0
        return [r, g, b, a]
    return [1.0, 1.0, 1.0, 1.0]

def run_material(args):
    obj_name = args.get("object_name")
    if not obj_name:
        return {"status": "error", "message": "Argument 'object_name' is required"}

    obj = bpy.data.objects.get(obj_name)
    if not obj:
        return {"status": "error", "message": f"Object '{obj_name}' not found"}

    bpy.ops.ed.undo_push(message="MCP Manage Material")

    action = args.get("action", "create_and_assign").lower()
    mat_name = args.get("material_name")

    if action == "assign_existing":
        if not mat_name or mat_name not in bpy.data.materials:
            return {"status": "error", "message": f"Material '{mat_name}' does not exist"}
        mat = bpy.data.materials[mat_name]
        if not obj.data.materials:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat
        return {"status": "ok", "message": f"Assigned material '{mat.name}' to '{obj.name}'"}

    # create_and_assign or update_principled
    if action == "update_principled":
        if obj.data.materials and obj.data.materials[0]:
            mat = obj.data.materials[0]
        elif mat_name and mat_name in bpy.data.materials:
            mat = bpy.data.materials[mat_name]
        else:
            return {"status": "error", "message": "No active material found to update"}
    else: # create_and_assign
        name = mat_name or f"{obj.name}_Mat"
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        if not obj.data.materials:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat

    # Configure Principled BSDF node
    bsdf = None
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                bsdf = node
                break

    if bsdf:
        if "base_color" in args:
            c = args["base_color"]
            if isinstance(c, str):
                c = hex_to_rgba(c)
            elif isinstance(c, (list, tuple)) and len(c) == 3:
                c = [c[0], c[1], c[2], 1.0]
            bsdf.inputs['Base Color'].default_value = c

        if "metallic" in args:
            bsdf.inputs['Metallic'].default_value = float(args["metallic"])

        if "roughness" in args:
            bsdf.inputs['Roughness'].default_value = float(args["roughness"])

        if "emission_color" in args:
            c = args["emission_color"]
            if isinstance(c, str):
                c = hex_to_rgba(c)
            elif isinstance(c, (list, tuple)) and len(c) == 3:
                c = [c[0], c[1], c[2], 1.0]
            if 'Emission Color' in bsdf.inputs:
                bsdf.inputs['Emission Color'].default_value = c
            elif 'Emission' in bsdf.inputs:
                bsdf.inputs['Emission'].default_value = c

        if "emission_strength" in args:
            if 'Emission Strength' in bsdf.inputs:
                bsdf.inputs['Emission Strength'].default_value = float(args["emission_strength"])

        if "transmission" in args:
            if 'Transmission Weight' in bsdf.inputs:
                bsdf.inputs['Transmission Weight'].default_value = float(args["transmission"])
            elif 'Transmission' in bsdf.inputs:
                bsdf.inputs['Transmission'].default_value = float(args["transmission"])

        if "alpha" in args:
            if 'Alpha' in bsdf.inputs:
                bsdf.inputs['Alpha'].default_value = float(args["alpha"])

    return {
        "status": "ok",
        "message": f"Successfully setup material '{mat.name}' on '{obj.name}'",
        "material": mat.name
    }
"#;

    match call_python_tool(py, code, "run_material", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Material operation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during material operation: {}", e)),
    }
}
