use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::call_python_tool;
use pyo3::prelude::*;
use serde_json::json;

pub fn execute_script(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    let code_to_run = match args.get("code").and_then(|c| c.as_str()) {
        Some(c) => c,
        None => return ToolCallResponse::error("Argument 'code' is required"),
    };

    let auto_undo = args
        .get("auto_undo")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let wrapper_code = r#"
import bpy
import io
import sys
import time
import traceback
import json

def run_script(args):
    user_code = args.get("code", "")
    auto_undo = args.get("auto_undo", True)

    if auto_undo:
        try:
            bpy.ops.ed.undo_push(message="MCP Script Execution")
        except Exception:
            pass

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    local_vars = {"bpy": bpy}
    start_time = time.perf_counter()

    try:
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        exec(user_code, local_vars)
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        
        result_val = local_vars.get("result", None)
        try:
            json.dumps(result_val)
        except (TypeError, OverflowError):
            result_val = repr(result_val)

        return {
            "status": "ok",
            "result": result_val,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_ms": duration_ms
        }
    except Exception as ex:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return {
            "status": "error",
            "message": str(ex),
            "traceback": traceback.format_exc(),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "duration_ms": duration_ms
        }
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
"#;

    let payload = json!({
        "code": code_to_run,
        "auto_undo": auto_undo
    });

    match call_python_tool(py, wrapper_code, "run_script", payload) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if val.get("status").and_then(|s| s.as_str()) == Some("error") {
                    let msg = val
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Script execution failed");
                    let tb = val.get("traceback").and_then(|t| t.as_str()).unwrap_or("");
                    let stdout = val.get("stdout").and_then(|t| t.as_str()).unwrap_or("");
                    let stderr = val.get("stderr").and_then(|t| t.as_str()).unwrap_or("");
                    ToolCallResponse::error(format!(
                        "{}\nTraceback:\n{}\nStdout:\n{}\nStderr:\n{}",
                        msg, tb, stdout, stderr
                    ))
                } else {
                    ToolCallResponse::json(&val)
                }
            } else {
                ToolCallResponse::text(json_str)
            }
        }
        Err(e) => ToolCallResponse::error(format!("Python error executing script: {}", e)),
    }
}
