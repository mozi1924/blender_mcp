// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

use crate::bridge::channel::{ToolCallResponse, ToolContent};
use pyo3::prelude::*;
use serde_json::Value;

use once_cell::sync::Lazy;
use std::sync::RwLock;

pub const RUNTIME_MODULE: &str = "blender_mcp_runtime";

static RUNTIME_MODULE_NAME: Lazy<RwLock<Option<String>>> = Lazy::new(|| RwLock::new(None));

pub fn set_runtime_module_name(name: String) {
    if let Ok(mut lock) = RUNTIME_MODULE_NAME.write() {
        *lock = Some(name);
    }
}

/// Import the runtime module.
///
/// Supports namespaced Blender extensions (e.g. ``bl_ext.*.blender_mcp_runtime``)
/// without modifying ``sys.path`` or triggering policy violations.
pub fn import_runtime(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    // 1. If an explicit runtime module name has been registered, try that first.
    if let Ok(lock) = RUNTIME_MODULE_NAME.read() {
        if let Some(ref name) = *lock {
            if let Ok(module) = py.import(name.as_str()) {
                return Ok(module);
            }
        }
    }

    // 2. Discover dynamically from sys.modules (e.g. bl_ext.*.blender_mcp_runtime).
    if let Ok(sys) = py.import("sys") {
        if let Ok(modules) = sys.getattr("modules") {
            if let Ok(dict) = modules.downcast::<pyo3::types::PyDict>() {
                let mut candidate: Option<String> = None;
                for (key, _) in dict.iter() {
                    if let Ok(name) = key.extract::<String>() {
                        if name == RUNTIME_MODULE || name.ends_with(&format!(".{RUNTIME_MODULE}")) {
                            let is_blext = name.starts_with("bl_ext.");
                            if is_blext || candidate.is_none() {
                                candidate = Some(name);
                                if is_blext {
                                    break;
                                }
                            }
                        }
                    }
                }
                if let Some(name) = candidate {
                    if let Ok(module) = py.import(name.as_str()) {
                        set_runtime_module_name(name);
                        return Ok(module);
                    }
                }
            }
        }
    }

    // 3. Fallback to direct import (e.g. in standalone tests).
    py.import(RUNTIME_MODULE)
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
        return ToolCallResponse::json_error(&value);
    }

    // Tools that return multi-modal content (e.g. blender_capture) emit an
    // MCP-shaped `content` array.  Convert it directly instead of wrapping the
    // base64 payload in a JSON text block.
    if let Some(items) = value.get("content").and_then(Value::as_array) {
        if let Ok(content) = serde_json::from_value::<Vec<ToolContent>>(Value::Array(items.clone()))
        {
            return ToolCallResponse {
                is_error: false,
                content,
            };
        }
    }

    ToolCallResponse::json(&value)
}

pub fn runtime_error(prefix: &str, err: PyErr) -> ToolCallResponse {
    ToolCallResponse::error(format!(
        "{prefix}: {err}. Make sure the 'blender_mcp_runtime' package is next to the \
         blender_mcp_core extension (it ships with the add-on)."
    ))
}
