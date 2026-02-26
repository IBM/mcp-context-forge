// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// A2A Service - High-performance agent invocation with PyO3 bindings

use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::Duration;

use pyo3::conversion::IntoPyObject;
use pyo3::prelude::*;
use pyo3::types::PyList;
use pythonize::{depythonize, pythonize};
use serde_json::Value as JsonValue;
use tracing::{info, warn};

mod auth;
mod errors;
mod invoker;
mod metrics;
mod queue;

pub use crate::auth::{apply_invoke_auth, AuthConfig, InvokeAuth};
pub use crate::errors::A2AError;
pub use crate::invoker::{A2AInvokeRequest, A2AInvokeResult, A2AInvoker, A2AResponse};
pub use crate::metrics::{AggregateMetrics, MetricsCollector};

/// Python-exposed A2A response.
/// When the response body was valid JSON, `parsed` is set so Python can skip json.loads.
/// We keep `body` (raw string) for non-2xx responses, parse failures, and error messages;
/// Python uses `result.body` in _parse_a2a_response_json and when building error text.
#[pyclass(module = "gateway_rs.a2a_service")]
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

/// Result of invoke: list of (id, response, duration_secs). Converted to Python list when the future completes.
struct InvokeResultList(Vec<(usize, A2AResponsePy, f64)>);

impl<'py> IntoPyObject<'py> for InvokeResultList {
    type Target = PyAny;
    type Output = Bound<'py, PyAny>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let list = PyList::empty(py);
        for (id, resp, duration_secs) in self.0 {
            let item = Py::new(py, resp)?;
            list.append((id, item, duration_secs))?;
        }
        Ok(list.into_any())
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

/// Invoke 1..N A2A agents via the Rust reqwest-based invoker.
/// Auth is applied in Rust (no Python fallback). Python does DB and decryption only; passes decrypted auth here.
/// `requests` must be a list of (id, base_url, auth_query_params, auth_headers, request_payload) where
///   auth_query_params is None or dict of str->str, auth_headers is dict of str->str.
/// Returns list of (id, A2AResponsePy, duration_secs) in order.
#[pyfunction]
fn invoke<'py>(
    py: Python<'py>,
    requests: &Bound<'_, PyAny>,
    timeout_secs: f64,
) -> PyResult<Bound<'py, PyAny>> {
    let list = requests
        .cast::<PyList>()
        .map_err(|_| {
            pyo3::exceptions::PyTypeError::new_err(
                "invoke() requires a list of (id, base_url, auth_query_params, auth_headers, payload)",
            )
        })?;

    let mut rust_requests = Vec::with_capacity(list.len());
    for (i, item) in list.iter().enumerate() {
        let raw: (
            usize,
            String,
            Option<HashMap<String, String>>,
            HashMap<String, String>,
            JsonValue,
        ) = depythonize(&item)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("request[{}]: {}", i, e)))?;
        let (id, base_url, auth_query_params, auth_headers, payload) = raw;
        let auth = InvokeAuth {
            query_params: auth_query_params,
            headers: auth_headers,
        };
        let (url, headers) = apply_invoke_auth(&base_url, &auth).map_err(|e| {
            warn!("request[{}]: apply_invoke_auth failed: {}", i, e);
            pyo3::exceptions::PyValueError::new_err(format!("request[{}]: {}", i, e))
        })?;
        let body = serde_json::to_vec(&payload).map_err(|e| {
            warn!("request[{}]: payload serialization failed: {}", i, e);
            pyo3::exceptions::PyValueError::new_err(format!("request[{}]: {}", i, e))
        })?;
        rust_requests.push(A2AInvokeRequest {
            id,
            url,
            body,
            headers,
        });
    }

    let timeout = Duration::from_secs_f64(timeout_secs);
    let inv = get_invoker();
    let n = rust_requests.len();
    info!("A2A invoke started: {} requests", n);

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let results = inv.invoke(rust_requests, timeout).await;
        let ok_count = results.iter().filter(|r| r.result.as_ref().map_or(false, |resp| resp.status_code == 200)).count();
        info!("A2A invoke completed: {} results ({} ok)", results.len(), ok_count);
        let out: Vec<(usize, A2AResponsePy, f64)> = results
            .into_iter()
            .map(|r| {
                let resp = match r.result {
                    Ok(resp) => A2AResponsePy {
                        status_code: resp.status_code,
                        body: resp.body,
                        parsed: resp.parsed,
                    },
                    Err(e) => {
                        tracing::warn!("A2A invoke request id={} failed: {}", r.id, e);
                        A2AResponsePy {
                            status_code: 502,
                            body: e.to_string(),
                            parsed: None,
                        }
                    }
                };
                (r.id, resp, r.duration_secs)
            })
            .collect();
        Ok(InvokeResultList(out))
    })
}

/// Build A2A metrics batch and success IDs for Python to push to buffer and DB.
/// Recording (what to record) is done in Rust; buffer and DB writes stay in Python.
///
/// Args:
///   entries: list of (agent_id, interaction_type, status_code, body, duration_secs)
///   end_time_utc_seconds: timestamp for metrics (Unix seconds)
///
/// Returns:
///   (metrics_list, success_agent_ids)
///   metrics_list: list of (a2a_agent_id, timestamp_secs, response_time, is_success, interaction_type, error_message)
///   success_agent_ids: list of agent_id for successful invokes (for last_interaction updates)
#[pyfunction]
fn build_a2a_metrics_batch<'py>(
    py: Python<'py>,
    entries: &Bound<'_, PyAny>,
    end_time_utc_seconds: f64,
) -> PyResult<Bound<'py, PyAny>> {
    let list = entries
        .cast::<PyList>()
        .map_err(|_| pyo3::exceptions::PyTypeError::new_err("entries must be a list of (agent_id, interaction_type, status_code, body, duration_secs)"))?;

    let metrics_out = PyList::empty(py);
    let success_ids = PyList::empty(py);

    for (i, item) in list.iter().enumerate() {
        let (agent_id, interaction_type, status_code, body, duration_secs): (String, String, u16, String, f64) =
            depythonize(&item).map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("entries[{}]: {}", i, e)))?;

        let success = status_code == 200;
        let error_message: Option<String> = if success {
            None
        } else if body.is_empty() {
            Some("Internal Server Error".to_string())
        } else {
            Some(body)
        };

        let metric_item = (
            agent_id.clone(),
            end_time_utc_seconds,
            duration_secs,
            success,
            interaction_type.clone(),
            error_message,
        )
            .into_pyobject(py)?;
        metrics_out.append(metric_item)?;

        if success {
            success_ids.append(agent_id)?;
        }
    }

    Ok((metrics_out, success_ids).into_pyobject(py)?.into_any())
}

/// A2A Service module
#[pymodule]
pub fn a2a_service(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<A2AResponsePy>()?;
    m.add_function(pyo3::wrap_pyfunction!(invoke, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(build_a2a_metrics_batch, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(crate::queue::init_queue, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(crate::queue::submit_queue, m)?)?;
    Ok(())
}
