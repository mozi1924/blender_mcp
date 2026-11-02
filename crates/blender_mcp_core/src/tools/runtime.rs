// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

//! Bridge to the persistent Python runtime.
//!
//! The Rust side no longer contains any Blender-specific tool logic or tool
//! schemas.  It forwards calls by name and caches the catalog that Python
//! builds from live RNA.

use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::{call_runtime, import_runtime, respond, runtime_error};
use crate::tools::ToolDefinition;
use pyo3::prelude::*;

pub fn tool_definitions(py: Python<'_>) -> Result<Vec<ToolDefinition>, String> {
    let module = import_runtime(py).map_err(|e| e.to_string())?;
    let json_str: String = module
        .call_method0("list_tools_json")
        .map_err(|e| e.to_string())?
        .extract()
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&json_str).map_err(|e| e.to_string())
}

pub fn set_profile(py: Python<'_>, profile: &str) -> Result<(), String> {
    let module = import_runtime(py).map_err(|e| e.to_string())?;
    module
        .call_method1("set_tool_profile", (profile,))
        .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn execute(py: Python<'_>, name: &str, args: &serde_json::Value) -> ToolCallResponse {
    match call_runtime(py, name, args) {
        Ok(json_str) => respond(json_str),
        Err(err) => runtime_error(&format!("Tool '{name}' failed"), err),
    }
}

/// Internal pseudo-tool used by ``tools/list`` fallbacks.
pub fn list_tools_response(py: Python<'_>) -> ToolCallResponse {
    match tool_definitions(py) {
        Ok(defs) => match serde_json::to_value(&defs) {
            Ok(value) => ToolCallResponse::text(value.to_string()),
            Err(err) => ToolCallResponse::error(err.to_string()),
        },
        Err(err) => ToolCallResponse::error(err),
    }
}
