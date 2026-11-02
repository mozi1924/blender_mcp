// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

//! Thin Rust adapters for the adaptive Python runtime.
//!
//! Blender knowledge (operator parameters, enums, modifier/node catalogs,
//! property coercion) lives in `addon/blender_mcp/blender_mcp_runtime`; these
//! functions only marshal JSON across the PyO3 boundary and normalize errors.

use crate::bridge::channel::ToolCallResponse;
use crate::tools::helper::{call_runtime, respond, runtime_error};
use crate::tools::ToolDefinition;
use pyo3::prelude::*;

fn invoke(py: Python<'_>, tool: &str, args: &serde_json::Value) -> ToolCallResponse {
    match call_runtime(py, tool, args) {
        Ok(json_str) => respond(json_str),
        Err(err) => runtime_error(&format!("Runtime tool '{tool}' failed"), err),
    }
}

pub fn describe(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    invoke(py, "blender_describe", &args)
}

pub fn run_operator(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    invoke(py, "blender_run_operator", &args)
}

pub fn create_primitive(py: Python<'_>, args: serde_json::Value) -> ToolCallResponse {
    invoke(py, "blender_create_primitive", &args)
}

/// Ask the runtime for its MCP tool catalog.  Used by `tools/list` so live
/// enums/schemas can override the static fallback definitions.
pub fn runtime_tool_definitions(py: Python<'_>) -> Result<Vec<ToolDefinition>, String> {
    let module = super::helper::import_runtime(py).map_err(|e| e.to_string())?;
    let json_str: String = module
        .call_method0("list_tools_json")
        .map_err(|e| e.to_string())?
        .extract()
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&json_str).map_err(|e| e.to_string())
}

pub fn list_tools_response(py: Python<'_>) -> ToolCallResponse {
    match runtime_tool_definitions(py) {
        Ok(defs) => match serde_json::to_value(&defs) {
            Ok(value) => ToolCallResponse::text(value.to_string()),
            Err(err) => ToolCallResponse::error(err.to_string()),
        },
        Err(err) => ToolCallResponse::error(err),
    }
}
