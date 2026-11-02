use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;

pub fn manage_modifier(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def run_modifier(args):
    obj_name = args.get("object_name")
    if not obj_name:
        return {"status": "error", "message": "Argument 'object_name' is required"}

    obj = bpy.data.objects.get(obj_name)
    if not obj:
        return {"status": "error", "message": f"Object '{obj_name}' not found"}

    bpy.ops.ed.undo_push(message="MCP Manage Modifier")

    action = args.get("action", "add").lower()
    mod_name = args.get("modifier_name")
    mod_type = args.get("modifier_type", "").upper()
    props = args.get("properties", {})

    if action == "add":
        if not mod_type:
            return {"status": "error", "message": "Argument 'modifier_type' is required for action 'add'"}
        actual_name = mod_name or mod_type.title()
        mod = obj.modifiers.new(name=actual_name, type=mod_type)
        for k, v in props.items():
            if k == "object":
                target_obj = bpy.data.objects.get(v)
                if target_obj:
                    setattr(mod, "object", target_obj)
            elif hasattr(mod, k):
                try:
                    setattr(mod, k, v)
                except Exception as ex:
                    print(f"Warning: could not set {k}={v} on modifier: {ex}")
        return {
            "status": "ok",
            "message": f"Added modifier '{mod.name}' ({mod.type}) to '{obj.name}'",
            "modifier": {"name": mod.name, "type": mod.type}
        }

    elif action == "configure":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}

        for k, v in props.items():
            if k == "object":
                target_obj = bpy.data.objects.get(v)
                if target_obj:
                    setattr(mod, "object", target_obj)
            elif hasattr(mod, k):
                try:
                    setattr(mod, k, v)
                except Exception as ex:
                    print(f"Warning: could not set {k}={v} on modifier: {ex}")
        return {"status": "ok", "message": f"Configured modifier '{mod.name}' on '{obj.name}'"}

    elif action == "apply":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
            return {"status": "ok", "message": f"Applied modifier '{mod.name}' on '{obj.name}'"}
        except Exception as ex:
            return {"status": "error", "message": f"Failed to apply modifier: {ex}"}

    elif action == "remove":
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if not mod and mod_type:
            for m in obj.modifiers:
                if m.type == mod_type:
                    mod = m
                    break
        if not mod:
            return {"status": "error", "message": f"Modifier '{mod_name or mod_type}' not found on '{obj.name}'"}
        name_removed = mod.name
        obj.modifiers.remove(mod)
        return {"status": "ok", "message": f"Removed modifier '{name_removed}' from '{obj.name}'"}

    else:
        return {"status": "error", "message": f"Unknown action '{action}'. Allowed: add, configure, apply, remove"}
"#;

    match call_python_tool(py, code, "run_modifier", args) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Modifier operation failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during modifier operation: {}", e)),
    }
}
