// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// A2A Service - High-performance agent invocation with PyO3 bindings

use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::Duration;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pythonize::{depythonize, pythonize};
use serde_json::Value as JsonValue;

mod auth;
mod errors;
mod invoker;
mod metrics;

pub use crate::auth::AuthConfig;
pub use crate::errors::A2AError;
pub use crate::invoker::{A2AInvoker, A2AResponse};
pub use crate::metrics::{AggregateMetrics, MetricsCollector};

/// Python-exposed A2A response.
/// When the response body was valid JSON, `parsed` is set so Python can skip json.loads.
/// We keep `body` (raw string) for non-2xx responses, parse failures, and error messages;
/// Python uses `result.body` in _parse_a2a_response_json and when building error text.
#[pyclass(module = "mcpgateway_rust.services.a2a_service")]
pub struct A2AResponsePy {
    #[pyo3(get)]
    pub status_code: u16,

    #[pyo3(get)]
    pub body: String,

    /// Parsed JSON (dict/list/etc.) when body was valid JSON; None otherwise.
    parsed: Option<JsonValue>,
}

#[pymethods]
impl A2AResponsePy {
    /// Return the parsed response body as a Python dict/list, or None if body was not valid JSON.
    #[getter(parsed)]
    fn get_parsed(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.parsed {
            Some(v) => Ok(pythonize(py, v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.unbind()),
            None => Ok(py.None()),
        }
    }
}

static INVOKER: OnceLock<A2AInvoker> = OnceLock::new();

fn get_invoker() -> &'static A2AInvoker {
    INVOKER.get_or_init(|| {
        let client = reqwest::Client::builder()
            .build()
            .expect("reqwest client");
        let metrics = std::sync::Arc::new(MetricsCollector::new());
        A2AInvoker::new(client, metrics)
    })
}

fn py_dict_to_headers(dict: &Bound<'_, PyDict>) -> PyResult<HashMap<String, String>> {
    let mut out = HashMap::new();
    for (k, v) in dict.iter() {
        let key = k.extract::<String>()?;
        let val = v.extract::<String>()?;
        out.insert(key, val);
    }
    Ok(out)
}

/// Invoke a single A2A agent via the Rust reqwest-based invoker.
/// Accepts request_payload as a Python dict (or list); serializes to JSON in Rust.
/// Response includes optional parsed JSON when body is valid JSON.
#[pyfunction]
fn invoke<'py>(
    py: Python<'py>,
    agent_url: &str,
    request_payload: &Bound<'_, PyAny>,
    headers: &Bound<'_, PyDict>,
    timeout_secs: f64,
) -> PyResult<Bound<'py, PyAny>> {
    let headers_map = py_dict_to_headers(headers)?;
    let agent_url = agent_url.to_string();
    let body_value: JsonValue = depythonize(request_payload)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let body = serde_json::to_vec(&body_value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let timeout = Duration::from_secs_f64(timeout_secs);
    let inv = get_invoker();

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = inv.invoke(&agent_url, &body, &headers_map, timeout).await
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(A2AResponsePy {
            status_code: result.status_code,
            body: result.body,
            parsed: result.parsed,
        })
    })
}

/// Invoke multiple A2A agents concurrently via the Rust reqwest-based invoker.
/// Each request is (agent_url: str, request_payload: dict, headers: dict).
/// Returns a list of A2AResponsePy in the same order as requests.
/// On transport/Rust error, the corresponding item has status_code 0 and body set to the error message.
#[pyfunction]
fn invoke_batch<'py>(
    py: Python<'py>,
    requests: &Bound<'_, PyAny>,
    timeout_secs: f64,
) -> PyResult<Bound<'py, PyAny>> {
    let list = requests.cast::<PyList>()?;
    let mut rust_requests: Vec<(String, Vec<u8>, HashMap<String, String>)> =
        Vec::with_capacity(list.len());
    for item in list.iter() {
        let url: String = item.get_item(0)?.extract()?;
        let payload = item.get_item(1)?;
        let headers_item = item.get_item(2)?;
        let headers_dict = headers_item.cast::<PyDict>()?;
        let body_value: JsonValue = depythonize(&payload)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let body = serde_json::to_vec(&body_value)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let headers_map = py_dict_to_headers(&headers_dict)?;
        rust_requests.push((url, body, headers_map));
    }
    let timeout = Duration::from_secs_f64(timeout_secs);
    let inv = get_invoker();

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let results = inv.invoke_batch(rust_requests, timeout).await;
        let mut out = Vec::with_capacity(results.len());
        for r in results {
            let resp_py = match r {
                Ok(resp) => A2AResponsePy {
                    status_code: resp.status_code,
                    body: resp.body,
                    parsed: resp.parsed,
                },
                Err(e) => A2AResponsePy {
                    status_code: 0,
                    body: e.to_string(),
                    parsed: None,
                },
            };
            out.push(resp_py);
        }
        Ok(out)
    })
}

/// A2A Service module
#[pymodule]
pub fn a2a_service(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<A2AResponsePy>()?;
    m.add_function(pyo3::wrap_pyfunction!(invoke, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(invoke_batch, m)?)?;
    Ok(())
}
