mod error;
mod http {
    pub mod streamable;
}

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};

#[pyfunction]
fn prepare_streamable_http_context(
    py: Python<'_>,
    scope: Bound<'_, PyAny>,
) -> PyResult<Py<PyDict>> {
    let scope_dict = scope.downcast::<PyDict>()?;

    let modified_path = scope_dict
        .get_item("modified_path")?
        .and_then(|v| v.extract::<String>().ok());
    let raw_path = scope_dict
        .get_item("path")?
        .and_then(|v| v.extract::<String>().ok());
    let path = modified_path.or(raw_path).unwrap_or_default();

    let headers_obj = scope_dict.get_item("headers")?;
    let mut headers_pairs: Vec<(String, String)> = Vec::new();

    if let Some(headers) = headers_obj {
        if let Ok(header_list) = headers.downcast::<PyList>() {
            for item in header_list {
                if let Ok(tuple) = item.downcast::<PyTuple>() {
                    if tuple.len() == 2 {
                        let key = tuple
                            .get_item(0)?
                            .downcast::<PyBytes>()?
                            .as_bytes()
                            .to_vec();
                        let value = tuple
                            .get_item(1)?
                            .downcast::<PyBytes>()?
                            .as_bytes()
                            .to_vec();

                        let key_str = String::from_utf8_lossy(&key).to_string();
                        let value_str = String::from_utf8_lossy(&value).to_string();
                        headers_pairs.push((key_str, value_str));
                    }
                }
            }
        }
    }

    let normalized_headers = http::streamable::normalize_headers(headers_pairs);
    let server_id = http::streamable::extract_server_id(&path);
    let is_mcp_path = http::streamable::is_mcp_path(&path);

    let result = PyDict::new(py);
    result.set_item("path", path)?;
    result.set_item("server_id", server_id)?;
    result.set_item("is_mcp_path", is_mcp_path)?;

    let py_headers = PyDict::new(py);
    for (k, v) in normalized_headers {
        py_headers.set_item(k, v)?;
    }
    result.set_item("headers", py_headers)?;

    Ok(result.unbind())
}

#[pyfunction]
fn start_streamable_http_transport(scope: Bound<'_, PyAny>, _receive: Bound<'_, PyAny>, send: Bound<'_, PyAny>) -> PyResult<bool> {
    let py = scope.py();
    let scope_dict = scope.downcast::<PyDict>()?;

    let modified_path = scope_dict
        .get_item("modified_path")?
        .and_then(|v| v.extract::<String>().ok());
    let raw_path = scope_dict
        .get_item("path")?
        .and_then(|v| v.extract::<String>().ok());
    let path = modified_path.or(raw_path).unwrap_or_default();

    if !http::streamable::is_mcp_path(&path) {
        return Ok(false);
    }

    let method = scope_dict
        .get_item("method")?
        .and_then(|v| v.extract::<String>().ok())
        .unwrap_or_default()
        .to_ascii_uppercase();

    // Handle CORS preflight directly in Rust to avoid a full Python fallback path.
    // For non-OPTIONS methods, Python session manager remains the source of truth.
    if method != "OPTIONS" {
        return Ok(false);
    }

    let headers = PyList::empty(py);
    headers.append(("content-length".as_bytes(), "0".as_bytes()))?;
    headers.append(("access-control-allow-origin".as_bytes(), "*".as_bytes()))?;
    headers.append(("access-control-allow-methods".as_bytes(), "GET,POST,OPTIONS".as_bytes()))?;
    headers.append((
        "access-control-allow-headers".as_bytes(),
        "authorization,content-type,mcp-session-id,last-event-id".as_bytes(),
    ))?;

    let start_msg = PyDict::new(py);
    start_msg.set_item("type", "http.response.start")?;
    start_msg.set_item("status", 204)?;
    start_msg.set_item("headers", headers)?;

    let body_msg = PyDict::new(py);
    body_msg.set_item("type", "http.response.body")?;
    body_msg.set_item("body", "".as_bytes())?;

    schedule_async_send(py, &send, &start_msg)?;
    schedule_async_send(py, &send, &body_msg)?;

    Ok(true)
}

#[pymodule]
fn mcpgateway_transport_rs(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(prepare_streamable_http_context, m)?)?;
    m.add_function(wrap_pyfunction!(start_streamable_http_transport, m)?)?;
    Ok(())
}
