// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! # A2A Service
//!
//! High-performance Agent-to-Agent (A2A) invocation with PyO3 bindings for the MCP Gateway.
//!
//! ## Overview
//!
//! This crate provides the Rust core for HTTP invocation of A2A agents: Python prepares requests
//! (URL, pre-serialized JSON body, and encrypted auth blobs when AUTH_ENCRYPTION_SECRET is set) and calls the PyO3
//! `try_submit_invoke` entry point; Rust performs auth decryption (when secret set),
//! HTTP POST, retry, circuit breaker, per-agent metrics, and returns responses. Auth decryption
//! and application are done in Rust only; no Python fallback.
//!
//! ## Python API (PyO3)
//!
//! - **`build_a2a_metrics_batch(entries, end_time_utc_seconds)`** — Build metrics tuples and success IDs for Python to push to buffer/DB.
//! - **`get_agent_metrics(agent_id)`** — Return per-agent aggregated metrics, or `None` if no data.
//! - **`reset_metrics()`** — Reset in-memory invocation metrics (call when Python resets DB metrics).
//! - **`init_invoker(max_concurrent, max_retries)`** — Configure invoker before first use (call once at startup).
//! - **`init_queue(max_concurrent)`** — Initialize the invoke queue (call once at startup).
//! - **`init_queue(max_concurrent, max_queued)`** — Initialize the batch queue (call once at startup). `max_queued`: optional cap; when set and full, `try_submit_invoke` raises `QueueFullError`.
//! - **`try_submit_invoke(requests, timeout_secs)`** — Submit a batch with pre-serialized JSON body bytes (avoids serde_json in Rust).

use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use pyo3::conversion::IntoPyObject;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use pythonize::{depythonize, pythonize};
use serde_json::Value as JsonValue;
use log::warn;

// Queue-specific exceptions for stable cross-language error handling.
pyo3::create_exception!(gateway_rs.a2a_service, QueueFullError, pyo3::exceptions::PyRuntimeError);
pyo3::create_exception!(gateway_rs.a2a_service, QueueNotInitializedError, pyo3::exceptions::PyRuntimeError);
pyo3::create_exception!(gateway_rs.a2a_service, QueueShutdownError, pyo3::exceptions::PyRuntimeError);

mod auth;
mod circuit;
mod errors;
mod eviction;
mod invoker;
mod metrics;
mod queue;

pub use crate::auth::{apply_invoke_auth, decrypt_auth, decrypt_map_values, AuthConfig, InvokeAuth};
pub use crate::errors::A2AError;
pub use crate::invoker::{A2AInvokeRequest, A2AInvokeResult, A2AInvoker, A2AResponse, InvokerConfig};
pub use crate::metrics::{AggregateMetrics, AgentMetrics, MetricsCollector};

/// Parsed Python request tuple with pre-serialized body bytes.
struct ParsedRequestBytes {
    id: usize,
    base_url: String,
    auth_query_params: Option<HashMap<String, String>>,
    auth_headers: HashMap<String, String>,
    body: Vec<u8>,
    correlation_id: Option<String>,
    traceparent: Option<String>,
    agent_name: Option<String>,
    agent_id: Option<String>,
    interaction_type: Option<String>,
    scope_id: Option<String>,
    request_id: Option<String>,
}


/// Metric row for DB persistence (agent_id, timestamp_secs, response_time, is_success, interaction_type, error_message).
struct MetricRow {
    agent_id: String,
    timestamp_secs: f64,
    response_time: f64,
    is_success: bool,
    interaction_type: String,
    error_message: Option<String>,
}

/// Build a PyValueError for a request field with consistent message format.
fn request_field_error(i: usize, e: impl std::fmt::Display) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(format!("request[{}]: {}", i, e))
}


/// Parse a plain (non-encrypted) request tuple into ParsedRequestBytes. Pads missing fields with None/empty.
fn parse_plain_bytes_request(item: &Bound<'_, PyAny>, len: usize, i: usize) -> PyResult<ParsedRequestBytes> {
    if len < 5 || !matches!(len, 5 | 7 | 8 | 10 | 11 | 12) {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "request[{}]: expected tuple of length 5, 7, 8, 10, 11 or 12, got {}",
            i, len
        )));
    }
    let id: usize = depythonize(&item.get_item(0)?).map_err(|e| request_field_error(i, e))?;
    let base_url: String = depythonize(&item.get_item(1)?).map_err(|e| request_field_error(i, e))?;
    let auth_query_params: Option<HashMap<String, String>> =
        depythonize(&item.get_item(2)?).map_err(|e| request_field_error(i, e))?;
    let mut auth_headers: HashMap<String, String> =
        depythonize(&item.get_item(3)?).ok().unwrap_or_default();
    let body: Vec<u8> = depythonize(&item.get_item(4)?).map_err(|e| request_field_error(i, e))?;
    let correlation_id: Option<String> = if len >= 7 { depythonize(&item.get_item(5)?).ok() } else { None };
    let traceparent: Option<String> = if len >= 7 { depythonize(&item.get_item(6)?).ok() } else { None };
    if let Some(ref t) = traceparent {
        auth_headers.insert("traceparent".to_string(), t.clone());
    }
    let agent_name = if len >= 8 { depythonize(&item.get_item(7)?).ok() } else { None };
    let agent_id = if len >= 10 { depythonize(&item.get_item(8)?).ok() } else { None };
    let interaction_type = if len >= 10 { depythonize(&item.get_item(9)?).ok() } else { None };
    let scope_id = if len >= 11 { depythonize(&item.get_item(10)?).ok() } else { None };
    let request_id = if len >= 12 { depythonize(&item.get_item(11)?).ok() } else { None };
    Ok(ParsedRequestBytes {
        id,
        base_url,
        auth_query_params,
        auth_headers,
        body,
        correlation_id,
        traceparent,
        agent_name,
        agent_id,
        interaction_type,
        scope_id,
        request_id,
    })
}

/// Python-exposed A2A response.
/// When the response body was valid JSON, `parsed` is set so Python can skip json.loads.
/// We keep `body` (raw string) for non-2xx responses, parse failures, and error messages;
/// Python uses `result.body` in _parse_a2a_response_json and when building error text.
/// When the request failed (e.g. timeout, circuit open), unified error fields are set so
/// Python can return the same shape as Phase 1 (error, code, agent_name, status_code, details).
#[pyclass(module = "gateway_rs.a2a_service")]
pub struct A2AResponsePy {
    #[pyo3(get)]
    pub status_code: u16,

    #[pyo3(get)]
    pub body: String,

    /// Parsed JSON (dict/list/etc.) when body was valid JSON; None otherwise.
    parsed: Option<JsonValue>,

    /// Stable error code when invocation failed: timeout, circuit_open, oversized_response, http, auth, other.
    #[pyo3(get)]
    pub error_code: Option<String>,

    /// True when invocation succeeded (HTTP 2xx); false when failed (unified error shape).
    #[pyo3(get)]
    pub success: bool,

    /// Error message for API (unified shape); set when success is false.
    #[pyo3(get)]
    pub error: Option<String>,

    /// Error code for API (unified shape); same as error_code when success is false.
    #[pyo3(get)]
    pub code: Option<String>,

    /// Agent name for unified error response (from request).
    #[pyo3(get)]
    pub agent_name: Option<String>,

    /// Optional details (e.g. retry count) for unified error response.
    details: Option<JsonValue>,

    /// Metric row for DB persistence (Rust single source). Set when agent_id and interaction_type were provided in the request.
    metric_row: Option<MetricRow>,
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

    /// Return optional details dict for unified error response, or None.
    #[getter(details)]
    fn get_details(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.details {
            Some(v) => Ok(pythonize(py, v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.unbind()),
            None => Ok(py.None()),
        }
    }

    /// Return optional metric row (agent_id, timestamp_secs, response_time, is_success, interaction_type, error_message) for DB persistence, or None.
    #[getter(metric_row)]
    fn get_metric_row(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.metric_row {
            Some(row) => {
                let tup = (
                    row.agent_id.as_str(),
                    row.timestamp_secs,
                    row.response_time,
                    row.is_success,
                    row.interaction_type.as_str(),
                    row.error_message.as_deref(),
                );
                Ok(pythonize(py, &tup).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.unbind())
            }
            None => Ok(py.None()),
        }
    }

    /// Return the response as a unified result dict (same shape as Phase 1 DB errors). No normalization needed in Python.
    /// Success: status_code, body, parsed. Error: status_code, error, code, agent_name, details (optional).
    fn to_unified_result(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let dict = PyDict::new(py);
        dict.set_item("status_code", self.status_code)?;
        if self.success {
            dict.set_item("body", self.body.as_str())?;
            match &self.parsed {
                Some(v) => dict.set_item("parsed", pythonize(py, v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.unbind())?,
                None => dict.set_item("parsed", py.None())?,
            }
        } else {
            dict.set_item("error", self.error.as_deref().unwrap_or(self.body.as_str()))?;
            dict.set_item("code", self.code.as_deref().unwrap_or("agent_error"))?;
            if let Some(ref name) = self.agent_name {
                dict.set_item("agent_name", name.as_str())?;
            }
            if let Some(ref d) = self.details {
                dict.set_item("details", pythonize(py, d).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.unbind())?;
            }
        }
        Ok(dict.into_any().unbind())
    }
}

/// Result of invoke: list of (id, response, duration_secs). Converted to a Python list when the future completes.
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
/// Optional config set by Python at startup (max_concurrent, max_retries). First call to init_invoker wins.
static INVOKER_CONFIG: OnceLock<InvokerConfig> = OnceLock::new();

/// Initialize the A2A invoker with concurrency and retry limits. Call once at startup (e.g. when A2A is enabled).
/// Subsequent calls are no-ops; the first call wins. If never called, the invoker is created with defaults on first invoke.
#[pyfunction]
fn init_invoker(max_concurrent: usize, max_retries: u32) -> PyResult<()> {
    let _ = INVOKER_CONFIG.get_or_init(|| {
        let mut config = InvokerConfig::default();
        config.max_concurrent = Some(max_concurrent);
        config.max_retries = max_retries;
        config
    });
    Ok(())
}

/// Used by the batch queue worker to run HTTP; not part of the Python API.
pub(crate) fn get_invoker() -> &'static A2AInvoker {
    INVOKER.get_or_init(|| {
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("reqwest client");
        let metrics = std::sync::Arc::new(MetricsCollector::with_capacity(Some(10_000)));
        let config = INVOKER_CONFIG.get().cloned().unwrap_or_default();
        A2AInvoker::with_config(client, metrics, config)
    })
}

/// Parse Python request list into Rust A2AInvokeRequest list (bytes payload).
/// Payload is pre-serialized JSON bytes (to avoid serde_json in Rust).
fn parse_requests_bytes(list: &Bound<'_, PyList>, auth_secret_override: Option<String>) -> PyResult<Vec<A2AInvokeRequest>> {
    let auth_secret: Option<&str> = match auth_secret_override.as_deref() {
        Some(s) if !s.is_empty() => Some(s),
        _ => queue::get_auth_secret(),
    };
    let mut rust_requests = Vec::with_capacity(list.len());
    for (i, item) in list.iter().enumerate() {
        let len = item
            .cast::<PyList>()
            .map(|l| l.len())
            .or_else(|_| item.cast::<PyTuple>().map(|t| t.len()))
            .map_err(|_| pyo3::exceptions::PyValueError::new_err(format!("request[{}]: expected list or tuple", i)))?;
        let parsed: ParsedRequestBytes = if let Some(secret) = auth_secret {
            if len < 5 || len > 12 {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "request[{}]: expected tuple of length 5..12, got {}",
                    i, len
                )));
            }
            let id: usize = depythonize(&item.get_item(0)?).map_err(|e| request_field_error(i, e))?;
            let base_url: String = depythonize(&item.get_item(1)?).map_err(|e| request_field_error(i, e))?;
            let enc_query: Option<HashMap<String, String>> =
                depythonize(&item.get_item(2)?).map_err(|e| request_field_error(i, e))?;
            let enc_headers: Option<String> = depythonize(&item.get_item(3)?).map_err(|e| request_field_error(i, e))?;
            let auth_query_params = enc_query
                .map(|m| crate::auth::decrypt_map_values(&m, secret))
                .transpose()
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("request[{}]: auth decrypt: {}", i, e)))?;
            let mut auth_headers = enc_headers
                .map(|s| crate::auth::decrypt_auth(&s, secret))
                .transpose()
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("request[{}]: auth decrypt: {}", i, e)))?
                .unwrap_or_default();
            let body: Vec<u8> = depythonize(&item.get_item(4)?).map_err(|e| request_field_error(i, e))?;
            let correlation_id: Option<String> = if len >= 7 { depythonize(&item.get_item(5)?).ok() } else { None };
            let traceparent: Option<String> = if len >= 7 { depythonize(&item.get_item(6)?).ok() } else { None };
            let agent_name = if len >= 8 { depythonize(&item.get_item(7)?).ok() } else { None };
            let agent_id = if len >= 10 { depythonize(&item.get_item(8)?).ok() } else { None };
            let interaction_type = if len >= 10 { depythonize(&item.get_item(9)?).ok() } else { None };
            let scope_id = if len >= 11 { depythonize(&item.get_item(10)?).ok() } else { None };
            let request_id = if len >= 12 { depythonize(&item.get_item(11)?).ok() } else { None };
            auth_headers.insert("Content-Type".to_string(), "application/json".to_string());
            if let Some(ref c) = correlation_id {
                auth_headers.insert("X-Correlation-ID".to_string(), c.clone());
            }
            if let Some(ref t) = traceparent {
                auth_headers.insert("traceparent".to_string(), t.clone());
            }
            ParsedRequestBytes {
                id,
                base_url,
                auth_query_params,
                auth_headers,
                body,
                correlation_id,
                traceparent,
                agent_name,
                agent_id,
                interaction_type,
                scope_id,
                request_id,
            }
        } else {
            parse_plain_bytes_request(&item, len, i)?
        };
        let auth = InvokeAuth {
            query_params: parsed.auth_query_params,
            headers: parsed.auth_headers,
        };
        let (url, headers) = apply_invoke_auth(&parsed.base_url, &auth).map_err(|e| {
            warn!("request[{}]: apply_invoke_auth failed: {}", i, e);
            request_field_error(i, e)
        })?;
        rust_requests.push(A2AInvokeRequest {
            id: parsed.id,
            url,
            body: parsed.body,
            headers,
            correlation_id: parsed.correlation_id,
            traceparent: parsed.traceparent,
            agent_name: parsed.agent_name,
            agent_id: parsed.agent_id,
            interaction_type: parsed.interaction_type,
            scope_id: parsed.scope_id,
            request_id: parsed.request_id,
        });
    }
    Ok(rust_requests)
}


/// Extract success flag and optional error message from an invoke result.
fn success_and_error_message(r: &crate::invoker::A2AInvokeResult) -> (bool, Option<String>) {
    match r.result.as_ref() {
        Ok(resp) => (
            crate::errors::is_success_http_status(resp.status_code),
            if crate::errors::is_success_http_status(resp.status_code) {
                None
            } else if resp.body.is_empty() {
                Some("Internal Server Error".to_string())
            } else {
                Some(resp.body.clone())
            },
        ),
        Err(e) => (false, Some(e.to_string())),
    }
}

/// Build A2AResponsePy from an invoke result plus precomputed success, error_message, and optional metric_row.
fn result_to_a2a_response_py(
    r: &crate::invoker::A2AInvokeResult,
    success: bool,
    _error_message: Option<String>,
    metric_row: Option<MetricRow>,
) -> A2AResponsePy {
    match r.result.as_ref() {
        Ok(resp) => A2AResponsePy {
            status_code: resp.status_code,
            body: resp.body.clone(),
            parsed: resp.parsed.clone(),
            error_code: None,
            success,
            error: None,
            code: None,
            agent_name: None,
            details: None,
            metric_row,
        },
        Err(e) => {
            warn!("A2A invoke request id={} failed: {}", r.id, e);
            let code = e.error_code().to_string();
            A2AResponsePy {
                status_code: e.http_status(),
                body: e.to_string(),
                parsed: None,
                error_code: Some(code.clone()),
                success: false,
                error: Some(e.to_string()),
                code: Some(code),
                agent_name: r.agent_name.clone(),
                details: None,
                metric_row,
            }
        }
    }
}

/// Convert invoker results to the Python-facing list type.
/// On error, populates unified fields (success, error, code, agent_name, details) so Python
/// can return the same shape as Phase 1 DB errors.
/// When agent_id and interaction_type are present, sets metric_row for Python to persist (Rust single source).
fn invoke_results_to_py(results: Vec<crate::invoker::A2AInvokeResult>) -> InvokeResultList {
    let end_time_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    let out: Vec<(usize, A2AResponsePy, f64)> = results
        .into_iter()
        .map(|r| {
            let (success, error_message) = success_and_error_message(&r);
            let metric_row = match (r.agent_id.as_ref(), r.interaction_type.as_ref()) {
                (Some(aid), Some(it)) => Some(MetricRow {
                    agent_id: aid.clone(),
                    timestamp_secs: end_time_secs,
                    response_time: r.duration_secs,
                    is_success: success,
                    interaction_type: it.clone(),
                    error_message: error_message.clone(),
                }),
                _ => None,
            };
            let resp = result_to_a2a_response_py(&r, success, error_message, metric_row);
            (r.id, resp, r.duration_secs)
        })
        .collect();
    InvokeResultList(out)
}

/// Submit a batch to the A2A invoke queue with pre-serialized JSON body bytes.
/// Returns an awaitable that resolves to the same result shape as the direct invoker.
#[pyfunction]
#[pyo3(signature = (requests, timeout_secs, auth_secret=None))]
fn try_submit_invoke<'py>(
    py: Python<'py>,
    requests: &Bound<'_, PyAny>,
    timeout_secs: f64,
    auth_secret: Option<&Bound<'_, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let list = requests
        .cast::<PyList>()
        .map_err(|_| {
            pyo3::exceptions::PyTypeError::new_err(
                "try_submit_invoke() requires a list of (id, base_url, auth_query_params, auth_headers, body_bytes)",
            )
        })?;
    let secret: Option<String> = auth_secret.and_then(|a| depythonize::<String>(a).ok());
    let rust_requests = parse_requests_bytes(&list, secret)?;
    let timeout = Duration::from_secs_f64(timeout_secs);
    let rx = queue::try_submit_batch(rust_requests, timeout).map_err(|e| match e {
        queue::QueueError::Full => QueueFullError::new_err("A2A invoke queue full"),
        queue::QueueError::NotInitialized => QueueNotInitializedError::new_err("A2A invoke queue not initialized"),
        queue::QueueError::Shutdown => QueueShutdownError::new_err("A2A invoke queue shut down"),
    })?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let results = rx.await.map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("queue response channel closed: {}", e))
        })?;
        Ok(invoke_results_to_py(results))
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

        let success = crate::errors::is_success_http_status(status_code);
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

/// Return per-agent aggregated metrics for the given agent (id or URL), or None if no data.
/// Returns a dict: total_calls, successful_calls, failed_calls, total_latency_us, min_latency_us, max_latency_us.
#[pyfunction]
fn get_agent_metrics(agent_id: &str) -> Option<AggregateMetricsPy> {
    let inv = get_invoker();
    inv.metrics().get_aggregate(agent_id).map(AggregateMetricsPy::from)
}

/// Reset in-memory A2A invocation metrics (per-agent and global). Call from Python when DB metrics are reset.
/// Keeps Rust in-memory state in sync with Python's reset_metrics(db) for full-reset flows.
#[pyfunction]
fn reset_metrics() -> PyResult<()> {
    get_invoker().metrics().reset();
    Ok(())
}

/// Python-exposed aggregate metrics for one agent.
#[pyclass(module = "gateway_rs.a2a_service")]
pub struct AggregateMetricsPy {
    #[pyo3(get)]
    pub total_calls: u64,
    #[pyo3(get)]
    pub successful_calls: u64,
    #[pyo3(get)]
    pub failed_calls: u64,
    #[pyo3(get)]
    pub total_latency_us: u64,
    #[pyo3(get)]
    pub min_latency_us: u64,
    #[pyo3(get)]
    pub max_latency_us: u64,
}

impl From<AggregateMetrics> for AggregateMetricsPy {
    fn from(m: AggregateMetrics) -> Self {
        Self {
            total_calls: m.total_calls,
            successful_calls: m.successful_calls,
            failed_calls: m.failed_calls,
            total_latency_us: m.total_latency_us,
            min_latency_us: m.min_latency_us,
            max_latency_us: m.max_latency_us,
        }
    }
}

/// Initialize the A2A invoke batch queue. Call once at startup.
/// max_queued: optional cap; when set and queue is full, try_submit_invoke raises QueueFullError (map to 503).
/// auth_secret: when provided, request tuples must carry encrypted auth (query params and headers); we decrypt in Rust.
#[pyfunction]
fn init_queue(max_concurrent: usize, max_queued: Option<usize>, auth_secret: Option<String>) -> PyResult<()> {
    queue::init_queue(max_concurrent, max_queued, auth_secret);
    Ok(())
}

/// Graceful shutdown of the A2A invoke queue: stop accepting new work and drain pending jobs with the given timeout (seconds).
/// Returns an awaitable; call from Python lifespan after stopping the metrics buffer, before shutting down the A2A service.
#[pyfunction]
fn shutdown_queue<'py>(py: Python<'py>, timeout_secs: f64) -> PyResult<Bound<'py, PyAny>> {
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        queue::shutdown_queue(timeout_secs)
            .await
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    })
}

/// A2A Service module
#[pymodule]
pub fn a2a_service(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<A2AResponsePy>()?;
    m.add("QueueFullError", m.py().get_type::<QueueFullError>())?;
    m.add("QueueNotInitializedError", m.py().get_type::<QueueNotInitializedError>())?;
    m.add("QueueShutdownError", m.py().get_type::<QueueShutdownError>())?;
    m.add_function(pyo3::wrap_pyfunction!(try_submit_invoke, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(build_a2a_metrics_batch, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(get_agent_metrics, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(reset_metrics, m)?)?;
    m.add_class::<AggregateMetricsPy>()?;
    m.add_function(pyo3::wrap_pyfunction!(init_invoker, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(init_queue, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(shutdown_queue, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::parse_plain_bytes_request;
    use pyo3::types::{PyBytes, PyDict, PyDictMethods, PyTuple};
    use pyo3::IntoPyObject;
    use pyo3::Python;

    #[test]
    fn test_parse_plain_bytes_request_injects_traceparent_header() {
        unsafe {
            pyo3::ffi::Py_Initialize();
        }
        Python::try_attach(|py| {
            let headers = PyDict::new(py);
            headers.set_item("X-Test", "1").unwrap();
            let body = PyBytes::new(py, b"{}");
            let traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
            let tuple = PyTuple::new(
                py,
                [
                    0usize.into_pyobject(py).unwrap().into_any(),
                    "https://example.com".into_pyobject(py).unwrap().into_any(),
                    py.None().bind(py).clone(),
                    headers.into_any(),
                    body.into_any(),
                    "corr-1".into_pyobject(py).unwrap().into_any(),
                    traceparent.into_pyobject(py).unwrap().into_any(),
                ],
            )
            .unwrap();
            let parsed = parse_plain_bytes_request(&tuple.into_any(), 7, 0).unwrap();
            assert_eq!(
                parsed.auth_headers.get("traceparent").map(String::as_str),
                Some(traceparent)
            );
            assert_eq!(parsed.auth_headers.get("X-Test").map(String::as_str), Some("1"));
        })
        .expect("Python interpreter not initialized");
    }
}
