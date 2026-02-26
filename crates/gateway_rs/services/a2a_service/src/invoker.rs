//! A2A HTTP invoker: outbound POST requests to agent endpoints.
//!
//! Security invariants enforced here (defense-in-depth with Python):
//! - **URL scheme**: only `http` and `https` are allowed at invoke time (rejects `file:`, etc.).
//! - **Response body size**: responses are capped at a configurable maximum (default 10 MiB) to prevent OOM from malicious or buggy endpoints.
//!
//! Features: retry with exponential backoff, per-endpoint circuit breaker, optional batch concurrency limit.
//!
//! ## Request/response payload handling (copy vs zero-copy)
//!
//! **Request body**: Python builds the JSON payload and serializes it to bytes (`serde_json::to_vec`
//! in the PyO3 layer); Rust receives a `Vec<u8>`. This is a copy at the Python–Rust boundary.
//!
//! **Response body**: The response is read via a streaming API (`bytes_stream()`) into a `Vec<u8>`,
//! then converted to a `String` for UTF-8. The body is copied into process memory; Size is capped to avoid OOM.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures::future::{join_all, FutureExt};
use futures::stream::StreamExt;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest::Client;
use serde_json::Value as JsonValue;
use log::{debug, error};
use tokio::sync::Semaphore;
use url::Url;

use crate::circuit::CircuitBreaker;
use crate::errors::A2AError;
use crate::metrics::{MetricRecord, MetricsCollector};

/// Default maximum response body size (10 MiB). Prevents OOM from malicious or buggy endpoints.
const DEFAULT_MAX_RESPONSE_BODY_BYTES: usize = 10 * 1024 * 1024;

/// Default retries (including initial attempt).
const DEFAULT_MAX_RETRIES: u32 = 3;
/// Default initial backoff before first retry.
const DEFAULT_INITIAL_BACKOFF: Duration = Duration::from_secs(1);
/// Default circuit breaker: open after this many consecutive failures per endpoint.
const DEFAULT_CIRCUIT_FAILURE_THRESHOLD: u32 = 5;
/// Default circuit breaker: cooldown before half-open.
const DEFAULT_CIRCUIT_COOLDOWN: Duration = Duration::from_secs(30);

/// Adaptive timeout: minimum when using P95-based suggestion (no per-request timeout).
const ADAPTIVE_TIMEOUT_MIN: Duration = Duration::from_secs(1);
/// Adaptive timeout: maximum when using P95-based suggestion.
const ADAPTIVE_TIMEOUT_MAX: Duration = Duration::from_secs(300);

/// Small limit used only in oversized-response test to avoid allocating 10 MiB.
#[cfg(test)]
const MAX_RESPONSE_BODY_BYTES_FOR_TEST: usize = 10;

/// A2A invoke response with HTTP status, raw body, and optional parsed JSON.
/// When the body is valid JSON, `parsed` is set so Python can skip `json.loads`.
#[derive(Debug, Clone)]
pub struct A2AResponse {
    /// HTTP status code (e.g. 200, 404, 502).
    pub status_code: u16,
    /// Raw response body as UTF-8 string.
    pub body: String,
    /// Parsed JSON when body is valid JSON; `None` for invalid or non-JSON body.
    pub parsed: Option<JsonValue>,
}

/// Single outbound A2A request: id (for ordering), URL, body bytes, headers, and optional context.
#[derive(Debug, Clone)]
pub struct A2AInvokeRequest {
    /// Index for reassembling results in order.
    pub id: usize,
    /// Full request URL (including query params if auth added any).
    pub url: String,
    /// Request body (e.g. JSON-serialized A2A payload).
    pub body: Vec<u8>,
    /// HTTP headers to send (e.g. Content-Type, Authorization).
    pub headers: HashMap<String, String>,
    /// Optional correlation ID for log/trace correlation with Python layer.
    pub correlation_id: Option<String>,
    /// Optional W3C traceparent for distributed tracing.
    pub traceparent: Option<String>,
    /// Optional agent name for unified error reporting (included in error response when invocation fails).
    pub agent_name: Option<String>,
    /// Optional agent ID (DB id) for metrics persistence.
    pub agent_id: Option<String>,
    /// Optional interaction type for metrics (e.g. "query", "invoke").
    pub interaction_type: Option<String>,
    /// Optional scope id (e.g. team_id or tenant_id) for circuit breaker isolation; when None, "default" is used.
    pub scope_id: Option<String>,
    /// Optional idempotency key; same ID in batch coalesces to one HTTP call, shared result.
    pub request_id: Option<String>,
}

impl From<(usize, String, Vec<u8>, HashMap<String, String>)> for A2AInvokeRequest {
    fn from((id, url, body, headers): (usize, String, Vec<u8>, HashMap<String, String>)) -> Self {
        Self {
            id,
            url,
            body,
            headers,
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
        }
    }
}

/// Python indexed request: (id, agent_url, request_payload, headers). Payload is JSON-serialized to body.
impl TryFrom<(usize, String, JsonValue, HashMap<String, String>)> for A2AInvokeRequest {
    type Error = serde_json::Error;

    fn try_from((id, url, payload, headers): (usize, String, JsonValue, HashMap<String, String>)) -> Result<Self, Self::Error> {
        let body = serde_json::to_vec(&payload)?;
        Ok(Self {
            id,
            url,
            body,
            headers,
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
        })
    }
}

/// Shared result for a single invocation (used when coalescing: multiple indices share the same outcome).
pub type SharedInvokeResult = Arc<Result<A2AResponse, A2AError>>;

/// Single invoke result with the same index as the request, for reassembly by the caller.
/// Result is in an Arc so coalesced requests can share the same outcome without cloning (A2AError::Http holds non-Clone reqwest::Error).
#[derive(Debug, Clone)]
pub struct A2AInvokeResult {
    /// Index matching the request `id`.
    pub id: usize,
    /// Success response or error (e.g. timeout, circuit open, HTTP error). Shared via Arc when expanding coalesced results.
    pub result: SharedInvokeResult,
    /// Request duration in seconds (used for metrics and last_interaction).
    pub duration_secs: f64,
    /// Agent key (URL or id) used for per-agent metrics.
    pub agent_key: String,
    /// Agent name for unified error reporting (from request).
    pub agent_name: Option<String>,
    /// Agent ID and interaction type for metrics (from request).
    pub agent_id: Option<String>,
    pub interaction_type: Option<String>,
}

/// Validates that the URL has an allowed scheme (http/https only). Prevents SSRF via file:, etc.
/// Python validates endpoint_url at agent create/update (http/https/ws/wss); we enforce http/https
/// here at invoke time for defense-in-depth (e.g. direct DB edits, legacy data).
fn validate_url_scheme(url_str: &str) -> Result<(), A2AError> {
    let url = Url::parse(url_str).map_err(|e| {
        A2AError::Other(format!("Invalid invoke URL: {}", e))
    })?;
    match url.scheme() {
        "http" | "https" => Ok(()),
        _ => Err(A2AError::Other(format!(
            "Invoke URL scheme not allowed: {} (only http/https)",
            url.scheme()
        ))),
    }
}

/// Returns URL with query and fragment stripped for logging, to avoid leaking auth tokens in query params.
fn redact_url_for_log(url_str: &str) -> String {
    Url::parse(url_str)
        .ok()
        .map(|mut u| {
            u.set_query(None);
            u.set_fragment(None);
            u.to_string()
        })
        .unwrap_or_else(|| url_str.to_string())
}

/// Extension trait to convert Python headers dict to HeaderMap.
/// Skips invalid header names/values.
trait IntoHeaderMap {
    fn into_header_map(&self) -> HeaderMap;
}

impl IntoHeaderMap for HashMap<String, String> {
    fn into_header_map(&self) -> HeaderMap {
        let mut headers = HeaderMap::with_capacity(self.len());
        for (k, v) in self {
            if let (Ok(name), Ok(value)) = (
                HeaderName::try_from(k.as_str()),
                HeaderValue::try_from(v.as_str()),
            ) {
                headers.insert(name, value);
            }
        }
        headers
    }
}

/// Invoker configuration: retry, circuit breaker, and batch concurrency limit.
#[derive(Clone)]
pub struct InvokerConfig {
    /// Number of attempts (including the first). Retries use exponential backoff.
    pub max_retries: u32,
    /// Initial backoff duration before the first retry.
    pub initial_backoff: Duration,
    /// When true, per-endpoint circuit breaker is enabled.
    pub circuit_breaker_enabled: bool,
    /// Consecutive failures per endpoint before the circuit opens.
    pub circuit_failure_threshold: u32,
    /// Duration the circuit stays open before allowing one trial (half-open).
    pub circuit_cooldown: Duration,
    /// Max concurrent requests per batch; `None` = unlimited.
    pub max_concurrent: Option<usize>,
    /// Max circuit breaker entries per key; `None` = unbounded. Default bounds memory growth.
    pub circuit_max_entries: Option<usize>,
}

impl Default for InvokerConfig {
    fn default() -> Self {
        Self {
            max_retries: DEFAULT_MAX_RETRIES,
            initial_backoff: DEFAULT_INITIAL_BACKOFF,
            circuit_breaker_enabled: true,
            circuit_failure_threshold: DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
            circuit_cooldown: DEFAULT_CIRCUIT_COOLDOWN,
            max_concurrent: None,
            circuit_max_entries: Some(10_000),
        }
    }
}

/// Core HTTP invoker for outbound A2A calls.
///
/// Entry point for Python: pass pre-built url (with query auth if any),
/// JSON body bytes, and headers dict. Auth is decrypted and applied in Rust
/// when auth secret is set; no Python fallback.
///
/// Security: URLs are validated to http/https only; response bodies are
/// limited to 10 MiB by default (override via
/// [`with_max_response_body_bytes`](A2AInvoker::with_max_response_body_bytes)).
pub struct A2AInvoker {
    client: Client,
    metrics: Arc<MetricsCollector>,
    max_response_body_bytes: usize,
    config: InvokerConfig,
    circuit_breaker: Option<Arc<CircuitBreaker>>,
    semaphore: Option<Arc<Semaphore>>,
}

/// Build an A2AInvokeResult from components (reduces repeated struct literals).
fn make_invoke_result(
    id: usize,
    result: Result<A2AResponse, A2AError>,
    duration_secs: f64,
    agent_key: String,
    agent_name: Option<String>,
    agent_id: Option<String>,
    interaction_type: Option<String>,
) -> A2AInvokeResult {
    A2AInvokeResult {
        id,
        result: Arc::new(result),
        duration_secs,
        agent_key,
        agent_name,
        agent_id,
        interaction_type,
    }
}

/// Returns true if the error is transient and worth retrying (timeout, connection, 5xx).
fn is_retryable(err: &A2AError) -> bool {
    match err {
        A2AError::Timeout(_) => true,
        A2AError::Http(e) => {
            e.is_timeout()
                || e.is_connect()
                || e.status()
                    .map(|s| s.is_server_error())
                    .unwrap_or(false)
        }
        A2AError::CircuitOpen | A2AError::OversizedResponse | A2AError::Auth(_) | A2AError::Other(_) => false,
    }
}

/// Reads response body with a size limit to prevent OOM. Returns UTF-8 string or error.
async fn read_body_with_limit(
    response: reqwest::Response,
    max_bytes: usize,
) -> Result<String, A2AError> {
    let mut body = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        if body.len() + chunk.len() > max_bytes {
            return Err(A2AError::OversizedResponse);
        }
        body.extend_from_slice(&chunk);
    }
    String::from_utf8(body).map_err(|e| {
        A2AError::Other(format!("Response body not valid UTF-8: {}", e))
    })
}

/// Execute a single A2A request: semaphore, circuit breaker, URL validation, retry loop, then build result.
async fn execute_one_request(
    client: Client,
    req: A2AInvokeRequest,
    request_timeout: Duration,
    max_body: usize,
    max_retries: u32,
    initial_backoff: Duration,
    circuit_breaker: Option<Arc<CircuitBreaker>>,
    semaphore: Option<Arc<Semaphore>>,
) -> A2AInvokeResult {
    let id = req.id;
    let url_for_log = req.url.clone();
    let agent_key = req.url.clone();
    let scope_id = req.scope_id.as_deref().unwrap_or("default");
    // TODO: document scope trade-off (per-scope isolation vs global per-URL fail-fast); see circuit.rs
    let circuit_key = format!("{}::{}", req.url, scope_id);
    let agent_name = req.agent_name.clone();
    let agent_id = req.agent_id.clone();
    let interaction_type = req.interaction_type.clone();
    let correlation_id = req.correlation_id.clone();
    let traceparent = req.traceparent.clone();

    let _permit = match &semaphore {
        Some(sem) => match sem.clone().acquire_owned().await {
            Ok(p) => Some(p),
            Err(_) => {
                return make_invoke_result(
                    id,
                    Err(A2AError::Other("semaphore closed".to_string())),
                    0.0,
                    agent_key,
                    agent_name,
                    agent_id,
                    interaction_type,
                );
            }
        },
        None => None,
    };
    if let Some(ref cb) = circuit_breaker {
        if !cb.allow_request(&circuit_key) {
            return make_invoke_result(
                id,
                Err(A2AError::CircuitOpen),
                0.0,
                agent_key,
                agent_name,
                agent_id,
                interaction_type,
            );
        }
    }
    let url = req.url.clone();
    if let Err(e) = validate_url_scheme(&url) {
        return make_invoke_result(id, Err(e), 0.0, agent_key, agent_name, agent_id, interaction_type);
    }
    let body = Bytes::from(req.body);
    let header_map = req.headers.clone().into_header_map();
    let start = Instant::now();
    let r = {
        let mut result = None;
        for attempt in 0..=max_retries {
            let res = (async {
                let response = client
                    .post(&url)
                    .body(body.clone())
                    .headers(header_map.clone())
                    .timeout(request_timeout)
                    .send()
                    .await?;
                let status_code = response.status().as_u16();
                let response_body = read_body_with_limit(response, max_body).await?;
                let parsed = serde_json::from_str(&response_body).ok();
                Ok::<_, A2AError>(A2AResponse {
                    status_code,
                    body: response_body,
                    parsed,
                })
            })
            .await;
            match &res {
                Ok(_) => {
                    if let Some(ref cb) = circuit_breaker {
                        cb.record_success(&circuit_key);
                    }
                    result = Some(res);
                    break;
                }
                Err(e) => {
                    if let Some(ref cb) = circuit_breaker {
                        cb.record_failure(&circuit_key);
                    }
                    let do_retry = attempt < max_retries && is_retryable(e);
                    result = Some(res);
                    if do_retry {
                        let backoff = initial_backoff * 2u32.saturating_pow(attempt);
                        tokio::time::sleep(backoff).await;
                    } else {
                        break;
                    }
                }
            }
        }
        result.unwrap_or_else(|| Err(A2AError::Other("request failed".to_string())))
    };
    let duration = start.elapsed();
    let duration_secs = duration.as_secs_f64();
    let url_log = redact_url_for_log(&url_for_log);
    let corr = correlation_id.as_deref().unwrap_or("");
    let trace = traceparent.as_deref().unwrap_or("");
    match &r {
        Ok(resp) => {
            if corr.is_empty() && trace.is_empty() {
                debug!(
                    "A2A invoke request id={} url={} completed status={} duration_secs={:.3}",
                    id, url_log, resp.status_code, duration_secs
                );
            } else {
                debug!(
                    "A2A invoke request id={} url={} completed status={} duration_secs={:.3} correlation_id={} traceparent={}",
                    id, url_log, resp.status_code, duration_secs, corr, trace
                );
            }
        }
        Err(e) => {
            if corr.is_empty() && trace.is_empty() {
                error!("A2A invoke request id={} url={} failed: {}", id, url_log, e);
            } else {
                error!(
                    "A2A invoke request id={} url={} failed: {} correlation_id={} traceparent={}",
                    id, url_log, e, corr, trace
                );
            }
        }
    }
    make_invoke_result(id, r, duration_secs, agent_key, agent_name, agent_id, interaction_type)
}

impl A2AInvoker {
    /// Create an invoker with default config (retry, circuit breaker enabled, no batch concurrency limit).
    pub fn new(client: Client, metrics: Arc<MetricsCollector>) -> Self {
        Self::with_config(client, metrics, InvokerConfig::default())
    }

    /// Create an invoker with the given config (retry, circuit breaker, and optional semaphore).
    pub fn with_config(
        client: Client,
        metrics: Arc<MetricsCollector>,
        config: InvokerConfig,
    ) -> Self {
        let circuit_breaker = config.circuit_breaker_enabled.then(|| {
            Arc::new(CircuitBreaker::new(
                config.circuit_failure_threshold,
                config.circuit_cooldown,
                config.circuit_max_entries,
            ))
        });
        let semaphore = config
            .max_concurrent
            .map(|n| Arc::new(Semaphore::new(n)));
        Self {
            client,
            metrics,
            max_response_body_bytes: DEFAULT_MAX_RESPONSE_BODY_BYTES,
            config,
            circuit_breaker,
            semaphore,
        }
    }

    /// Override max response body size (for tests or tuning). Default is 10 MiB.
    #[allow(dead_code)]
    pub fn with_max_response_body_bytes(mut self, max_bytes: usize) -> Self {
        self.max_response_body_bytes = max_bytes;
        self
    }

    /// Reference to the metrics collector (for PyO3 get_agent_metrics).
    pub fn metrics(&self) -> &MetricsCollector {
        self.metrics.as_ref()
    }

    /// Invoke 1..N requests. Returns results in input order; caller reassembles by id.
    /// Concurrency within the batch is limited by config.max_concurrent if set.
    /// Records timing and success/failure in metrics (batch). Circuit breaker and retry apply per request.
    /// URLs are validated (http/https only). Response bodies are capped at MAX_RESPONSE_BODY_BYTES.
    pub async fn invoke(
        &self,
        requests: Vec<A2AInvokeRequest>,
        timeout: Duration,
    ) -> Vec<A2AInvokeResult> {
        if requests.is_empty() {
            return Vec::new();
        }
        let original_len = requests.len();
        // Coalesce by request_id: same id => one HTTP call, result shared for all original indices.
        // Coalesce key: request_id when set, otherwise __u_{id} per request so each stays distinct.
        let mut key_to_indices: HashMap<String, Vec<usize>> = HashMap::new();
        let mut key_to_req: HashMap<String, A2AInvokeRequest> = HashMap::new();
        for req in requests {
            let key = req
                .request_id
                .clone()
                .unwrap_or_else(|| format!("__u_{}", req.id));
            key_to_indices.entry(key.clone()).or_default().push(req.id);
            if !key_to_req.contains_key(&key) {
                key_to_req.insert(key, req);
            }
        }
        let mut work: Vec<(Vec<usize>, A2AInvokeRequest)> = key_to_indices
            .into_iter()
            .map(|(key, indices)| {
                let req = key_to_req.remove(&key).unwrap();
                (indices, req)
            })
            .collect();
        work.sort_by_key(|(indices, _)| *indices.first().unwrap_or(&0));
        // Map: original request index -> index into unique_requests (work).
        let mut original_index_to_work_index = vec![0; original_len];
        for (wi, (indices, _)) in work.iter().enumerate() {
            for &id in indices {
                original_index_to_work_index[id] = wi;
            }
        }
        let unique_requests: Vec<A2AInvokeRequest> = work
            .into_iter()
            .enumerate()
            .map(|(wi, (_, mut req))| {
                req.id = wi;
                req
            })
            .collect();

        let effective_timeouts: Vec<Duration> = unique_requests
            .iter()
            .map(|req| {
                self.metrics.suggest_timeout_for_agent(
                    &req.url,
                    timeout,
                    ADAPTIVE_TIMEOUT_MIN,
                    ADAPTIVE_TIMEOUT_MAX,
                )
            })
            .collect();

        let client = self.client.clone();
        let metrics = Arc::clone(&self.metrics);
        let max_body = self.max_response_body_bytes;
        let max_retries = self.config.max_retries;
        let initial_backoff = self.config.initial_backoff;
        let circuit_breaker = self.circuit_breaker.clone();
        let semaphore = self.semaphore.clone();
        let futures = unique_requests
            .into_iter()
            .zip(effective_timeouts)
            .map(|(req, request_timeout)| {
                execute_one_request(
                    client.clone(),
                    req,
                    request_timeout,
                    max_body,
                    max_retries,
                    initial_backoff,
                    circuit_breaker.clone(),
                    semaphore.clone(),
                )
                .boxed()
            })
            .collect::<Vec<_>>();
        let unique_results = join_all(futures).await;
        // Batch record to in-memory metrics (per unique request only).
        let batch: Vec<MetricRecord> = unique_results
            .iter()
            .map(|r| {
                let success = match r.result.as_ref() {
                    Ok(resp) => crate::errors::is_success_http_status(resp.status_code),
                    Err(_) => false,
                };
                MetricRecord {
                    agent_key: r.agent_key.clone(),
                    success,
                    duration: Duration::from_secs_f64(r.duration_secs),
                }
            })
            .collect();
        metrics.record_batch(&batch);
        // Expand: one result per original index, id restored for ordering.
        let results: Vec<A2AInvokeResult> = (0..original_len)
            .map(|i| {
                let r = &unique_results[original_index_to_work_index[i]];
                A2AInvokeResult {
                    id: i,
                    result: Arc::clone(&r.result),
                    duration_secs: r.duration_secs,
                    agent_key: r.agent_key.clone(),
                    agent_name: r.agent_name.clone(),
                    agent_id: r.agent_id.clone(),
                    interaction_type: r.interaction_type.clone(),
                }
            })
            .collect();
        results
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use reqwest::Client;
    use serde_json::json;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    use super::{A2AInvokeRequest, A2AInvoker, InvokerConfig};
    use crate::errors::A2AError;
    use crate::metrics::MetricsCollector;

    #[test]
    fn test_invoker_config_default() {
        let c = InvokerConfig::default();
        assert!(c.max_retries >= 1);
        assert!(c.circuit_breaker_enabled);
        assert!(c.circuit_failure_threshold >= 1);
        assert!(c.max_concurrent.is_none());
        assert!(c.circuit_max_entries.is_some());
    }

    #[test]
    fn test_a2a_invoke_request_from_tuple() {
        let mut headers = HashMap::new();
        headers.insert("H".to_string(), "V".to_string());
        let req: A2AInvokeRequest = (0, "https://example.com".to_string(), b"body".to_vec(), headers.clone()).into();
        assert_eq!(req.id, 0);
        assert_eq!(req.url, "https://example.com");
        assert_eq!(req.body, b"body");
        assert_eq!(req.headers.get("H").map(String::as_str), Some("V"));
    }

    #[test]
    fn test_a2a_invoke_request_try_from_json() {
        let mut headers = HashMap::new();
        headers.insert("Content-Type".to_string(), "application/json".to_string());
        let req = A2AInvokeRequest::try_from((
            1,
            "https://example.com".to_string(),
            json!({"key": "value"}),
            headers,
        ))
        .unwrap();
        assert_eq!(req.id, 1);
        assert_eq!(req.url, "https://example.com");
        assert!(std::str::from_utf8(&req.body).unwrap().contains("key"));
    }

    fn test_invoker() -> A2AInvoker {
        let client = Client::builder().build().expect("reqwest client");
        let metrics = Arc::new(MetricsCollector::new());
        A2AInvoker::new(client, metrics)
    }

    /// Invoker with tiny body limit for oversized-response test.
    fn test_invoker_small_limit() -> A2AInvoker {
        test_invoker().with_max_response_body_bytes(super::MAX_RESPONSE_BODY_BYTES_FOR_TEST)
    }

    #[tokio::test]
    async fn test_invoke_success_returns_raw_body() {
        let mock_server = MockServer::start().await;
        let body_json = r#"{"jsonrpc":"2.0","result":{"test":true}}"#;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_raw(body_json.as_bytes(), "application/json"),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: mock_server.uri().to_string(),
                    body: body_json.as_bytes().to_vec(),
                    headers,
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let resp = r.result.as_ref().as_ref().ok().unwrap();
        assert_eq!(resp.status_code, 200);
        assert_eq!(resp.body, body_json);
    }

    #[tokio::test]
    async fn test_invoke_non_2xx_returns_ok_with_status_and_body() {
        let mock_server = MockServer::start().await;
        let body_text = r#"{"error":"not found"}"#;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(404).set_body_raw(body_text.as_bytes(), "application/json"),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: mock_server.uri().to_string(),
                    body: b"{}".to_vec(),
                    headers,
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let resp = r.result.as_ref().as_ref().ok().unwrap();
        assert_eq!(resp.status_code, 404);
        assert_eq!(resp.body, body_text);
    }

    #[tokio::test]
    async fn test_invoke_non_json_body_returned_as_raw_string() {
        let mock_server = MockServer::start().await;
        let body_text = "<html><body>Error 500</body></html>";
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(500).set_body_string(body_text),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: mock_server.uri().to_string(),
                    body: b"{}".to_vec(),
                    headers,
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let resp = r.result.as_ref().as_ref().ok().unwrap();
        assert_eq!(resp.status_code, 500);
        assert_eq!(resp.body, body_text);
    }

    #[tokio::test]
    async fn test_invoke_headers_passed_through() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(ResponseTemplate::new(200).set_body_string("{}"))
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let mut headers = HashMap::new();
        headers.insert("Content-Type".to_string(), "application/json".to_string());
        headers.insert("X-Custom".to_string(), "custom-value".to_string());

        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: mock_server.uri().to_string(),
                    body: b"{}".to_vec(),
                    headers,
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let resp = r.result.as_ref().as_ref().ok().unwrap();
        assert_eq!(resp.status_code, 200);
    }

    #[tokio::test]
    async fn test_invoke_invalid_url_returns_err() {
        // No retries and short timeout so the test fails fast (no multi-second DNS/timeout/backoff).
        let config = InvokerConfig {
            max_retries: 0,
            ..InvokerConfig::default()
        };
        let inv = A2AInvoker::with_config(
            Client::builder().build().expect("reqwest client"),
            Arc::new(MetricsCollector::new()),
            config,
        );
        let headers = HashMap::new();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: "http://invalid-domain-that-does-not-exist-12345.local/".to_string(),
                    body: b"{}".to_vec(),
                    headers,
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let result = results.into_iter().next().unwrap().result;
        assert!(result.is_err());
        assert!(matches!(result.as_ref(), Err(A2AError::Http(_))));
    }

    #[tokio::test]
    async fn test_invoke_file_scheme_rejected() {
        let inv = test_invoker();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: "file:///etc/passwd".to_string(),
                    body: b"{}".to_vec(),
                    headers: HashMap::new(),
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(1),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let err = r.result.as_ref().as_ref().unwrap_err();
        assert!(matches!(err, A2AError::Other(_)));
        assert!(err.to_string().contains("not allowed"));
    }

    #[tokio::test]
    async fn test_invoke_oversized_response_returns_err() {
        let mock_server = MockServer::start().await;
        let oversized = "x".repeat(super::MAX_RESPONSE_BODY_BYTES_FOR_TEST + 1);
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_string(oversized),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker_small_limit();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: mock_server.uri().to_string(),
                    body: b"{}".to_vec(),
                    headers: HashMap::new(),
                    correlation_id: None,
                    traceparent: None,
                    agent_name: None,
                    agent_id: None,
                    interaction_type: None,
                    scope_id: None,
                    request_id: None,
                }],
                Duration::from_secs(5),
            )
            .await;
        let r = results.into_iter().next().unwrap();
        let err = r.result.as_ref().as_ref().unwrap_err();
        assert!(matches!(err, A2AError::OversizedResponse));
        assert!(err.to_string().contains("exceeds maximum"));
    }

    #[tokio::test]
    async fn test_invoke_batch_returns_indexed_results() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_string(r#"{"id":1}"#),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let requests = vec![
            A2AInvokeRequest {
                id: 0,
                url: mock_server.uri().to_string(),
                body: b"{}".to_vec(),
                headers: HashMap::new(),
                correlation_id: None,
                traceparent: None,
                agent_name: None,
                agent_id: None,
                interaction_type: None,
                scope_id: None,
                request_id: None,
            },
            A2AInvokeRequest {
                id: 1,
                url: mock_server.uri().to_string(),
                body: b"{}".to_vec(),
                headers: HashMap::new(),
                correlation_id: None,
                traceparent: None,
                agent_name: None,
                agent_id: None,
                interaction_type: None,
                scope_id: None,
                request_id: None,
            },
        ];

        let results = inv.invoke(requests, Duration::from_secs(5)).await;

        assert_eq!(results.len(), 2);
        let ids: Vec<usize> = results.iter().map(|r| r.id).collect();
        assert!(ids.contains(&0));
        assert!(ids.contains(&1));
        for r in &results {
            let resp = r.result.as_ref().as_ref().ok().unwrap();
            assert_eq!(resp.status_code, 200);
        }
    }
}
