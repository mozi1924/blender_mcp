// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

//! MCP tool registry.
//!
//! All tool implementations and schemas live in the Python runtime
//! (`addon/blender_mcp/blender_mcp_runtime`).  Rust owns:
//!   * the catalog cache populated at server start,
//!   * name-based forwarding of `tools/call`,
//!   * conversion of the runtime envelope into MCP content.
//!
//! Adding a tool therefore only requires a Python `registry.register(...)`
//! call; no Rust changes.

pub mod helper;
pub mod runtime;

use crate::bridge::channel::ToolCallResponse;
use once_cell::sync::Lazy;
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::sync::RwLock;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: serde_json::Value,
    /// MCP safety hints (readOnlyHint, destructiveHint, ...).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub annotations: Option<serde_json::Value>,
}

static TOOL_CACHE: Lazy<RwLock<Vec<ToolDefinition>>> = Lazy::new(|| RwLock::new(Vec::new()));

/// Rebuild the tool catalog from the live Python runtime.
pub fn refresh_tool_definitions(py: Python<'_>) -> Result<usize, String> {
    let definitions = runtime::tool_definitions(py)?;
    let count = definitions.len();
    *TOOL_CACHE
        .write()
        .unwrap_or_else(|poisoned| poisoned.into_inner()) = definitions;
    Ok(count)
}

/// Catalog snapshot populated by [`refresh_tool_definitions`].
pub fn get_tool_definitions() -> Vec<ToolDefinition> {
    TOOL_CACHE
        .read()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .clone()
}

pub fn execute_tool(py: Python<'_>, name: &str, args: serde_json::Value) -> ToolCallResponse {
    if name == "__list_tools__" {
        return runtime::list_tools_response(py);
    }
    runtime::execute(py, name, &args)
}
