use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;
use serde_json::json;

pub fn undo(py: Python<'_>, _args: serde_json::Value) -> ToolCallResponse {
    let code = r#"
import bpy

def run_undo(args):
    try:
        res = bpy.ops.ed.undo()
        return {"status": "ok", "message": f"Undo executed successfully ({res})"}
    except Exception as ex:
        return {"status": "error", "message": f"Failed to undo: {ex}"}
"#;

    match call_python_tool(py, code, "run_undo", json!({})) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Undo failed");
                    ToolCallResponse::error(msg)
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error during undo: {}", e)),
    }
}
