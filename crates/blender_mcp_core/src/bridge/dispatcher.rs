use crate::bridge::channel::recv_requests;
use crate::tools;
use pyo3::prelude::*;

pub fn dispatch_pending_tasks(py: Python<'_>, max_batch: usize) -> usize {
    let requests = recv_requests(max_batch);
    let count = requests.len();
    for req in requests {
        let resp = tools::execute_tool(py, &req.tool_name, req.arguments);
        let _ = req.responder.send(resp);
    }
    count
}
