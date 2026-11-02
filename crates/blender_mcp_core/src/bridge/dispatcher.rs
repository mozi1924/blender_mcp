use crate::bridge::channel::recv_requests;
use crate::tools;
use pyo3::prelude::*;

pub fn dispatch_pending_tasks(py: Python<'_>, max_batch: usize) -> usize {
    let requests = recv_requests(max_batch);
    let count = requests.len();
    for req in requests {
        // A panic in tool code must never unwind across the PyO3/Blender FFI
        // boundary (and must never strand the waiting HTTP request).
        let resp = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            tools::execute_tool(py, &req.tool_name, req.arguments)
        }))
        .unwrap_or_else(|panic| {
            let detail = if let Some(msg) = panic.downcast_ref::<&str>() {
                (*msg).to_string()
            } else if let Some(msg) = panic.downcast_ref::<String>() {
                msg.clone()
            } else {
                "unknown panic payload".to_string()
            };
            eprintln!(
                "[Blender MCP] Tool '{}' panicked: {}",
                req.tool_name, detail
            );
            crate::bridge::channel::ToolCallResponse::error(format!(
                "Internal error while executing '{}': {}",
                req.tool_name, detail
            ))
        });
        let _ = req.responder.send(resp);
    }
    count
}
