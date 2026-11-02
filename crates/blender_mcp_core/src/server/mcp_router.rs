use crate::bridge::channel::send_request;
use crate::server::protocol::JsonRpcRequest;
use crate::server::protocol::JsonRpcResponse;
use crate::tools;
use serde_json::json;
use std::time::Duration;

pub async fn handle_rpc_request(req: JsonRpcRequest) -> Option<JsonRpcResponse> {
    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => {
            let res = json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": false
                    }
                },
                "serverInfo": {
                    "name": "blender-mcp-rust",
                    "version": "0.2.0"
                },
                "instructions": "Connected to Blender 5.x via high-performance Rust MCP. Use semantic tools (blender_inspect, blender_create_primitive, blender_transform_object, blender_manage_modifier, blender_manage_material, blender_setup_scene, blender_capture, blender_execute_script) for high-fidelity 3D modeling and visual workflows."
            });
            Some(JsonRpcResponse::success(id, res))
        }

        "notifications/initialized" => {
            // Notifications do not receive responses
            None
        }

        "ping" => Some(JsonRpcResponse::success(id, json!({}))),

        "tools/list" => {
            let tools_list = tools::get_tool_definitions();
            Some(JsonRpcResponse::success(
                id,
                json!({ "tools": tools_list }),
            ))
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

            // Await tool execution on Blender's main thread (timeout 120s for long renders)
            match tokio::time::timeout(Duration::from_secs(120), rx).await {
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
                    "Tool execution timed out waiting for Blender main thread (120s)",
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
