use pyo3::prelude::*;
use std::ffi::CString;

pub fn call_python_tool(
    py: Python<'_>,
    code: &str,
    func_name: &str,
    args: serde_json::Value,
) -> PyResult<String> {
    let code_c = CString::new(code)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
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
