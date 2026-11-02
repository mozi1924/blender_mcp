// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::bridge::channel::ToolCallResponse;
use pyo3::prelude::*;
use serde_json::Value;
use std::ffi::CString;

pub const RUNTIME_MODULE: &str = "blender_mcp_runtime";

/// Import the runtime, adding the extension's directory to ``sys.path`` as a
/// fallback.  The add-on already does this, but this keeps direct\.so imports
/// (tests, embedding) working too.
pub fn import_runtime(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    match py.import(RUNTIME_MODULE) {
        Ok(module) => Ok(module),
        Err(first_err) => {
            let mut added = false;
            if let Ok(core) = py.import("blender_mcp_core") {
                if let Ok(file) = core.getattr("__file__").and_then(|v| v.extract::<String>()) {
                    if let Some(parent) = std::path::Path::new(&file).parent() {
                        if let Ok(sys) = py.import("sys") {
                            if let Ok(path) = sys.getattr("path") {
                                let _ = path.call_method1(
                                    "insert",
                                    (0, parent.to_string_lossy().to_string()),
                                );
                                added = true;
                            }
                        }
                    }
                }
            }
            if added {
                py.import(RUNTIME_MODULE).map_err(|_| first_err)
            } else {
                Err(first_err)
            }
        }
    }
}

/// Import the persistent Python runtime and dispatch a tool.
///
/// Unlike `call_python_tool`, this does **not** recompile a module per request:
/// `blender_mcp_runtime` (and all of its catalogs/caches) lives in
/// ``sys.modules`` for the lifetime of the Blender session.
pub fn call_runtime(py: Python<'_>, tool: &str, args: &serde_json::Value) -> PyResult<String> {
    let module = import_runtime(py)?;
    let payload = serde_json::to_string(args)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    // `dispatch_json` serializes at the FFI boundary (and stringifies any
    // exotic value with default=str), so Rust always receives one JSON string.
    let result = module.call_method1("dispatch_json", (tool, payload))?;
    result.extract::<String>()
}

/// Convert a runtime JSON envelope into an MCP tool response.
///
/// Errors keep their structured diagnostics (`unknown`, `valid_parameters`,
/// `created_object`, `traceback`, ...) but set `isError` so clients can react.
pub fn respond(json_str: String) -> ToolCallResponse {
    match serde_json::from_str::<Value>(&json_str) {
        Ok(value) => respond_value(value),
        Err(_) => ToolCallResponse::text(json_str),
    }
}

pub fn respond_value(value: Value) -> ToolCallResponse {
    if value.get("status").and_then(Value::as_str) == Some("error") {
        ToolCallResponse::json_error(&value)
    } else {
        ToolCallResponse::json(&value)
    }
}

pub fn runtime_error(prefix: &str, err: PyErr) -> ToolCallResponse {
    ToolCallResponse::error(format!(
        "{prefix}: {err}. Make sure the 'blender_mcp_runtime' package is next to the \
         blender_mcp_core extension (it ships with the add-on)."
    ))
}

/// Legacy helper kept for the still-migrating tools.  New/adaptive tools should
/// use [`call_runtime`] instead.
pub fn call_python_tool(
    py: Python<'_>,
    code: &str,
    func_name: &str,
    args: serde_json::Value,
) -> PyResult<String> {
    let code_c =
        CString::new(code).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let file_c = CString::new("tool.py").unwrap();
    let mod_c = CString::new("tool_module").unwrap();

    let module = PyModule::from_code(py, &code_c, &file_c, &mod_c)?;
    let run_fn = module.getattr(func_name)?;
    let json_mod = py.import("json")?;
    let py_args = json_mod.call_method1("loads", (args.to_string(),))?;
    let py_res = run_fn.call1((py_args,))?;
    let json_str: String = json_mod.call_method1("dumps", (py_res,))?.extract()?;
    Ok(json_str)
}
