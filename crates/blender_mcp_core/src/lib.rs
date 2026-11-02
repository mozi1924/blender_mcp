pub mod bridge;
pub mod server;
pub mod tools;

use pyo3::prelude::*;

#[pyfunction]
#[pyo3(signature = (host = None, port = None))]
fn start_server(host: Option<&str>, port: Option<u16>) -> PyResult<bool> {
    let host = host.unwrap_or("127.0.0.1");
    let port = port.unwrap_or(8765);
    match server::start(host, port) {
        Ok(()) => Ok(true),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e)),
    }
}

#[pyfunction]
fn stop_server() -> PyResult<bool> {
    match server::stop() {
        Ok(()) => Ok(true),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e)),
    }
}

#[pyfunction]
fn is_running() -> PyResult<bool> {
    Ok(server::is_running())
}

#[pyfunction]
#[pyo3(signature = (max_batch = 16))]
fn poll_tick(py: Python<'_>, max_batch: usize) -> PyResult<usize> {
    let count = bridge::dispatcher::dispatch_pending_tasks(py, max_batch);
    Ok(count)
}

#[pyfunction]
fn get_tools() -> PyResult<String> {
    let tool_defs = tools::get_tool_definitions();
    serde_json::to_string_pretty(&tool_defs)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn blender_mcp_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(start_server, m)?)?;
    m.add_function(wrap_pyfunction!(stop_server, m)?)?;
    m.add_function(wrap_pyfunction!(is_running, m)?)?;
    m.add_function(wrap_pyfunction!(poll_tick, m)?)?;
    m.add_function(wrap_pyfunction!(get_tools, m)?)?;
    Ok(())
}
