use crate::bridge::channel::{send_request, ToolContent};
use crate::server::protocol::JsonRpcRequest;
use crate::server::protocol::JsonRpcResponse;
use crate::tools;
use serde_json::json;
use std::time::Duration;

const SERVER_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Clone)]
pub struct RpcContext {
    pub protocol_version: String,
    pub session_id: Option<String>,
    pub tool_timeout: Duration,
}

pub async fn handle_rpc_request(req: JsonRpcRequest, ctx: &RpcContext) -> Option<JsonRpcResponse> {
    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => {
            let res = json!({
                "protocolVersion": ctx.protocol_version,
                "capabilities": {
                    "tools": {
                        "listChanged": false
                    }
                },
                "serverInfo": {
                    "name": "blender-mcp-rust",
                    "version": SERVER_VERSION
                },
                "instructions": "Connected to Blender 5.x via a high-performance Rust MCP server. The tool surface is adaptive: call blender_describe (target=operator/operators/modifier/node_types/primitives/render_engines) to read live RNA parameters and enum identifiers for the current Blender session. Use blender_run_operator for any bpy.ops function (including primitive_type creation and post-processing), blender_set for RNA property writes/transforms/materials, blender_manage_nodes for node DAGs, blender_manage_modifier for modifier stacks, blender_inspect for scene state, blender_capture for renders, and blender_execute_script as the escape hatch."
            });
            Some(JsonRpcResponse::success(id, res))
        }

        "notifications/initialized" | "notifications/cancelled" => {
            // Notifications do not receive responses.  Cancellation is
            // acknowledged but cannot abort a Python call already running on
            // Blender's main thread; it only stops queued work when the bridge
            // is extended with request ids.
            None
        }

        "ping" => Some(JsonRpcResponse::success(id, json!({}))),

        "tools/list" => {
            // Populated at start_server() from the Python runtime.  If the
            // cache is empty (e.g. runtime import was delayed), fall back to a
            // one-shot bridge request.
            let mut tool_list = tools::get_tool_definitions();
            if tool_list.is_empty() {
                if let Ok(rx) = send_request("__list_tools__".to_string(), json!({})) {
                    if let Ok(Ok(resp)) = tokio::time::timeout(Duration::from_secs(3), rx).await {
                        if !resp.is_error {
                            if let Some(ToolContent::Text { text }) = resp.content.first() {
                                tool_list =
                                    serde_json::from_str::<Vec<tools::ToolDefinition>>(text)
                                        .unwrap_or_default();
                            }
                        }
                    }
                }
            }

            Some(JsonRpcResponse::success(id, json!({ "tools": tool_list })))
        }

        "tools/call" => {
            let params = match req.params {
                Some(p) => p,
                None => {
                    return Some(JsonRpcResponse::error(
                        id,
                        -32602,
                        "Missing params for tools/call",
                    ))
                }
            };

            let name = match params.get("name").and_then(|v| v.as_str()) {
                Some(n) => n.to_string(),
                None => {
                    return Some(JsonRpcResponse::error(
                        id,
                        -32602,
                        "Missing tool 'name' in params",
                    ))
                }
            };

            let arguments = params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));

            let rx = match send_request(name, arguments) {
                Ok(rx) => rx,
                Err(err) => return Some(JsonRpcResponse::error(id, -32000, err)),
            };

            // Await tool execution on Blender's main thread.
            match tokio::time::timeout(ctx.tool_timeout, rx).await {
                Ok(Ok(tool_resp)) => {
                    let res_val = serde_json::to_value(&tool_resp).unwrap_or_else(|_| {
                        json!({
                            "isError": true,
                            "content": [{"type": "text", "text": "Failed to serialize response"}]
                        })
                    });
                    Some(JsonRpcResponse::success(id, res_val))
                }
                Ok(Err(_)) => Some(JsonRpcResponse::error(
                    id,
                    -32000,
                    "Blender main thread dropped response channel without replying",
                )),
                Err(_) => Some(JsonRpcResponse::error(
                    id,
                    -32000,
                    format!(
                        "Tool execution timed out waiting for Blender main thread ({}s)",
                        ctx.tool_timeout.as_secs()
                    ),
                )),
            }
        }

        _ => Some(JsonRpcResponse::error(
            id,
            -32601,
            format!("Method not found: {}", req.method),
        )),
    }
}
