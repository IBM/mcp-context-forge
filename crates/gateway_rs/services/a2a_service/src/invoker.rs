//! A2A HTTP invoker: outbound POST requests to agent endpoints.
//!
//! Security invariants enforced here (defense-in-depth with Python):
//! - **URL scheme**: only `http` and `https` are allowed at invoke time (rejects `file:`, etc.).
//! - **Response body size**: responses are capped at a configurable maximum (default 10 MiB) to prevent OOM from malicious or buggy endpoints.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::future::{join_all, FutureExt};
use futures::stream::StreamExt;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest::Client;
use serde_json::Value as JsonValue;
use tracing::{debug, error};
use url::Url;

use crate::errors::A2AError;
use crate::metrics::MetricsCollector;

/// Default maximum response body size (10 MiB). Prevents OOM from malicious or buggy endpoints.
const DEFAULT_MAX_RESPONSE_BODY_BYTES: usize = 10 * 1024 * 1024;

/// Small limit used only in oversized-response test to avoid allocating 10 MiB.
#[cfg(test)]
const MAX_RESPONSE_BODY_BYTES_FOR_TEST: usize = 10;

/// A2A invoke response with HTTP status, raw body, and optional parsed JSON.
/// When the body is valid JSON, `parsed` is set so Python can skip json.loads.
#[derive(Debug)]
pub struct A2AResponse {
    pub status_code: u16,
    pub body: String,
    /// Parsed JSON when body is valid JSON; None for invalid or non-JSON body.
    pub parsed: Option<JsonValue>,
}

/// Single outbound A2A request: id (for ordering), URL, body bytes, and headers.
#[derive(Debug, Clone)]
pub struct A2AInvokeRequest {
    pub id: usize,
    pub url: String,
    pub body: Vec<u8>,
    pub headers: HashMap<String, String>,
}

impl From<(usize, String, Vec<u8>, HashMap<String, String>)> for A2AInvokeRequest {
    fn from((id, url, body, headers): (usize, String, Vec<u8>, HashMap<String, String>)) -> Self {
        Self { id, url, body, headers }
    }
}

/// Python indexed request: (id, agent_url, request_payload, headers). Payload is JSON-serialized to body.
impl TryFrom<(usize, String, JsonValue, HashMap<String, String>)> for A2AInvokeRequest {
    type Error = serde_json::Error;

    fn try_from((id, url, payload, headers): (usize, String, JsonValue, HashMap<String, String>)) -> Result<Self, Self::Error> {
        let body = serde_json::to_vec(&payload)?;
        Ok(Self { id, url, body, headers })
    }
}

/// Single invoke result with the same index as the request, for reassembly by the caller.
#[derive(Debug)]
pub struct A2AInvokeResult {
    pub id: usize,
    pub result: Result<A2AResponse, A2AError>,
    /// Request duration for metrics (Python buffer + last_interaction).
    pub duration_secs: f64,
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

/// Core HTTP invoker for outbound A2A calls.
///
/// Entry point for Python: pass pre-built url (with query auth if any),
/// JSON body bytes, and headers dict. No auth logic in Rust—Python handles
/// decode_auth, apply_query_param_auth, etc.
///
/// Security: URLs are validated to http/https only; response bodies are
/// limited to 10 MiB by default (override via
/// [`with_max_response_body_bytes`](A2AInvoker::with_max_response_body_bytes)).
pub struct A2AInvoker {
    client: Client,
    metrics: Arc<MetricsCollector>,
    max_response_body_bytes: usize,
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
            return Err(A2AError::Other(
                "Response body exceeds maximum allowed size".to_string(),
            ));
        }
        body.extend_from_slice(&chunk);
    }
    String::from_utf8(body).map_err(|e| {
        A2AError::Other(format!("Response body not valid UTF-8: {}", e))
    })
}

impl A2AInvoker {
    pub fn new(client: Client, metrics: Arc<MetricsCollector>) -> Self {
        Self {
            client,
            metrics,
            max_response_body_bytes: DEFAULT_MAX_RESPONSE_BODY_BYTES,
        }
    }

    /// Override max response body size (for tests or tuning). Default is 10 MiB.
    #[allow(dead_code)]
    pub fn with_max_response_body_bytes(mut self, max_bytes: usize) -> Self {
        self.max_response_body_bytes = max_bytes;
        self
    }

    /// Invoke 1..N requests. Returns results in input order; caller reassembles by id.
    /// All requests run concurrently. Records timing and success/failure in metrics (batch).
    /// URLs are validated (http/https only). Response bodies are capped at MAX_RESPONSE_BODY_BYTES.
    pub async fn invoke(
        &self,
        requests: Vec<A2AInvokeRequest>,
        timeout: Duration,
    ) -> Vec<A2AInvokeResult> {
        if requests.is_empty() {
            return Vec::new();
        }
        let client = self.client.clone();
        let metrics = Arc::clone(&self.metrics);
        let max_body = self.max_response_body_bytes;
        let futures = requests
            .into_iter()
            .map(|req| {
                let client = client.clone();
                let id = req.id;
                let url_for_log = req.url.clone();
                async move {
                    let start = Instant::now();
                    let r = (async {
                        validate_url_scheme(&req.url)?;
                        let header_map = req.headers.into_header_map();
                        let response = client
                            .post(&req.url)
                            .body(req.body)
                            .headers(header_map)
                            .timeout(timeout)
                            .send()
                            .await?;
                        let status_code = response.status().as_u16();
                        let body = read_body_with_limit(response, max_body).await?;
                        let parsed = serde_json::from_str(&body).ok();
                        Ok::<_, A2AError>(A2AResponse { status_code, body, parsed })
                    })
                    .await;
                    let duration = start.elapsed();
                    let duration_secs = duration.as_secs_f64();
                    match &r {
                        Ok(resp) => {
                            debug!(
                                "A2A invoke request id={} url={} completed status={} duration_secs={:.3}",
                                id, url_for_log, resp.status_code, duration_secs
                            );
                        }
                        Err(e) => {
                            error!("A2A invoke request id={} url={} failed: {}", id, url_for_log, e);
                        }
                    }
                    A2AInvokeResult {
                        id,
                        result: r,
                        duration_secs,
                    }
                }
                .boxed()
            })
            .collect::<Vec<_>>();
        let results = join_all(futures).await;
        // Batch record to in-memory metrics (Python will push same to DB buffer).
        let mut batch = Vec::with_capacity(results.len());
        for r in &results {
            let success = r.result.as_ref().map_or(false, |resp| resp.status_code == 200);
            batch.push((success, Duration::from_secs_f64(r.duration_secs)));
        }
        metrics.record_batch(&batch);
        results
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use reqwest::Client;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    use super::{A2AInvokeRequest, A2AInvoker};
    use crate::errors::A2AError;
    use crate::metrics::MetricsCollector;

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
                }],
                Duration::from_secs(5),
            )
            .await;
        let result = results.into_iter().next().unwrap().result.unwrap();
        assert_eq!(result.status_code, 200);
        assert_eq!(result.body, body_json);
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
                }],
                Duration::from_secs(5),
            )
            .await;
        let result = results.into_iter().next().unwrap().result.unwrap();
        assert_eq!(result.status_code, 404);
        assert_eq!(result.body, body_text);
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
                }],
                Duration::from_secs(5),
            )
            .await;
        let result = results.into_iter().next().unwrap().result.unwrap();
        assert_eq!(result.status_code, 500);
        assert_eq!(result.body, body_text);
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
                }],
                Duration::from_secs(5),
            )
            .await;
        let result = results.into_iter().next().unwrap().result.unwrap();
        assert_eq!(result.status_code, 200);
    }

    #[tokio::test]
    async fn test_invoke_invalid_url_returns_err() {
        let inv = test_invoker();
        let headers = HashMap::new();
        let results = inv
            .invoke(
                vec![A2AInvokeRequest {
                    id: 0,
                    url: "http://invalid-domain-that-does-not-exist-12345.local/".to_string(),
                    body: b"{}".to_vec(),
                    headers,
                }],
                Duration::from_secs(1),
            )
            .await;
        let result = results.into_iter().next().unwrap().result;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), A2AError::Http(_)));
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
                }],
                Duration::from_secs(1),
            )
            .await;
        let err = results.into_iter().next().unwrap().result.unwrap_err();
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
                }],
                Duration::from_secs(5),
            )
            .await;
        let err = results.into_iter().next().unwrap().result.unwrap_err();
        assert!(matches!(err, A2AError::Other(_)));
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
            },
            A2AInvokeRequest {
                id: 1,
                url: mock_server.uri().to_string(),
                body: b"{}".to_vec(),
                headers: HashMap::new(),
            },
        ];

        let results = inv.invoke(requests, Duration::from_secs(5)).await;

        assert_eq!(results.len(), 2);
        let ids: Vec<usize> = results.iter().map(|r| r.id).collect();
        assert!(ids.contains(&0));
        assert!(ids.contains(&1));
        for r in &results {
            let resp = r.result.as_ref().unwrap();
            assert_eq!(resp.status_code, 200);
        }
    }
}
