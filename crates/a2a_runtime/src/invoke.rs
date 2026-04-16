// crates/a2a_runtime/src/invoke.rs

// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Core invoke execution with URL validation, body limits, retry, and log redaction.

use crate::circuit::CircuitBreaker;
use crate::config::RuntimeConfig;
use crate::errors::InvokeError;
use crate::metrics::MetricsCollector;
use reqwest::{Client, header::HeaderMap};
use serde_json::Value;
use std::collections::HashMap;
use std::time::{Duration, Instant};
use tracing::{info, warn};
use url::Url;

/// Optional resilience context passed to [`execute_invoke`].
///
/// When provided, the invoke loop checks the circuit breaker before sending
/// and records success/failure in both the circuit breaker and metrics
/// collector after each attempt.
pub struct InvokeContext<'a> {
    pub circuit: &'a CircuitBreaker,
    pub metrics: &'a MetricsCollector,
    /// Tenant/team scope used as part of the circuit-breaker key.
    pub scope_id: &'a str,
    /// Agent identifier used as the metrics key.
    pub agent_key: &'a str,
}

/// Result of a successful outbound invocation (even if the agent returned an error HTTP status).
#[derive(Debug, Clone)]
pub struct InvokeResult {
    pub status_code: u16,
    pub headers: HashMap<String, String>,
    pub json: Option<Value>,
    pub text: String,
}

/// Validate that the endpoint URL uses an allowed scheme (http or https).
fn validate_url_scheme(endpoint_url: &str) -> Result<(), InvokeError> {
    let parsed = Url::parse(endpoint_url)
        .map_err(|e| InvokeError::InvalidScheme(format!("cannot parse URL: {e}")))?;
    match parsed.scheme() {
        "http" | "https" => Ok(()),
        other => Err(InvokeError::InvalidScheme(other.to_string())),
    }
}

/// Redact query string and fragment from a URL for safe logging.
/// Replaces query with `?REDACTED` and drops fragment entirely.
pub fn redact_url_for_log(endpoint_url: &str) -> String {
    match Url::parse(endpoint_url) {
        Ok(mut parsed) => {
            if parsed.query().is_some() {
                parsed.set_query(Some("REDACTED"));
            }
            parsed.set_fragment(None);
            // Also redact userinfo
            let _ = parsed.set_username("");
            let _ = parsed.set_password(None);
            parsed.to_string()
        }
        Err(_) => "<invalid-url>".to_string(),
    }
}

/// Build a `reqwest::header::HeaderMap` from string pairs.
fn build_header_map(headers: &HashMap<String, String>) -> Result<HeaderMap, InvokeError> {
    use reqwest::header::{HeaderName, HeaderValue};
    let mut header_map = HeaderMap::new();
    for (name, value) in headers {
        let header_name = HeaderName::from_bytes(name.as_bytes()).map_err(|e| {
            InvokeError::InvalidHeader(format!("invalid header name '{name}': {e}"))
        })?;
        let header_value = HeaderValue::from_str(value).map_err(|e| {
            InvokeError::InvalidHeader(format!("invalid header value for '{name}': {e}"))
        })?;
        header_map.insert(header_name, header_value);
    }
    Ok(header_map)
}

/// Classify a `reqwest::Error` into an `InvokeError`.
fn classify_reqwest_error(err: reqwest::Error, timeout: Duration) -> InvokeError {
    if err.is_timeout() {
        InvokeError::Timeout(timeout)
    } else if err.is_connect() {
        InvokeError::Connection(err.to_string())
    } else {
        InvokeError::Other(err.to_string())
    }
}

/// Execute an outbound A2A invocation with URL validation, body size limit, and retry.
///
/// When `ctx` is `Some`, the circuit breaker is checked before the first
/// attempt and success/failure is recorded in both the circuit breaker and
/// the metrics collector.
pub async fn execute_invoke(
    client: &Client,
    config: &RuntimeConfig,
    endpoint_url: &str,
    request_headers: &HashMap<String, String>,
    json_body: &Value,
    timeout: Duration,
    ctx: Option<&InvokeContext<'_>>,
) -> Result<InvokeResult, InvokeError> {
    validate_url_scheme(endpoint_url)?;
    let header_map = build_header_map(request_headers)?;
    let redacted_url = redact_url_for_log(endpoint_url);
    let max_body = config.max_response_body_bytes;
    let max_retries = config.max_retries;
    let backoff_base = Duration::from_millis(config.retry_backoff_ms);

    // Circuit breaker gate — fail fast if the endpoint is known-broken.
    if let Some(c) = ctx {
        if !c.circuit.allow_request(endpoint_url, c.scope_id) {
            return Err(InvokeError::CircuitOpen);
        }
    }

    let invoke_start = Instant::now();
    let mut last_error: Option<InvokeError> = None;

    for attempt in 0..=max_retries {
        if attempt > 0 {
            let backoff = backoff_base * 2u32.saturating_pow(attempt - 1);
            warn!(
                attempt,
                max_retries,
                backoff_ms = backoff.as_millis() as u64,
                url = %redacted_url,
                "retrying A2A invoke after transient error"
            );
            tokio::time::sleep(backoff).await;
        }

        let result = client
            .post(endpoint_url)
            .headers(header_map.clone())
            .json(json_body)
            .timeout(timeout)
            .send()
            .await;

        let response = match result {
            Ok(resp) => resp,
            Err(err) => {
                let invoke_err = classify_reqwest_error(err, timeout);
                if invoke_err.is_retryable() && attempt < max_retries {
                    warn!(
                        attempt,
                        error_code = invoke_err.error_code(),
                        url = %redacted_url,
                        "transient error during A2A invoke"
                    );
                    last_error = Some(invoke_err);
                    continue;
                }
                return Err(invoke_err);
            }
        };

        let status_code = response.status().as_u16();

        // Retry on 5xx before reading the body.
        if (500..600).contains(&status_code) && attempt < max_retries {
            warn!(
                attempt,
                status_code,
                url = %redacted_url,
                "agent returned 5xx, will retry"
            );
            last_error = Some(InvokeError::AgentHttp(status_code));
            continue;
        }

        let response_headers = response
            .headers()
            .iter()
            .filter_map(|(name, value)| {
                value
                    .to_str()
                    .ok()
                    .map(|v| (name.as_str().to_string(), v.to_string()))
            })
            .collect::<HashMap<_, _>>();

        // Read response body with size limit.
        let content_length = response.content_length();
        if let Some(len) = content_length {
            if len > max_body {
                return Err(InvokeError::OversizedResponse { limit: max_body });
            }
        }

        let bytes = response
            .bytes()
            .await
            .map_err(|e| InvokeError::Other(format!("failed to read response body: {e}")))?;

        if bytes.len() as u64 > max_body {
            return Err(InvokeError::OversizedResponse { limit: max_body });
        }

        let json = serde_json::from_slice::<Value>(&bytes).ok();
        let text = String::from_utf8_lossy(&bytes).to_string();

        let is_success = (200..300).contains(&status_code);
        let elapsed = invoke_start.elapsed();

        if let Some(c) = ctx {
            if is_success {
                c.circuit.record_success(endpoint_url, c.scope_id);
            } else {
                c.circuit.record_failure(endpoint_url, c.scope_id);
            }
            c.metrics
                .record_invocation(c.agent_key, is_success, elapsed);
        }

        info!(
            status_code,
            body_bytes = bytes.len(),
            url = %redacted_url,
            "A2A invoke completed"
        );

        return Ok(InvokeResult {
            status_code,
            headers: response_headers,
            json,
            text,
        });
    }

    // All retries exhausted — record failure and return last error.
    let elapsed = invoke_start.elapsed();
    if let Some(c) = ctx {
        c.circuit.record_failure(endpoint_url, c.scope_id);
        c.metrics.record_invocation(c.agent_key, false, elapsed);
    }
    Err(last_error.unwrap_or_else(|| InvokeError::Other("all retries exhausted".to_string())))
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;
    use reqwest::Client;
    use serde_json::json;
    use wiremock::matchers::method;
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn validate_url_scheme_accepts_http() {
        assert!(validate_url_scheme("http://example.com/invoke").is_ok());
    }

    #[test]
    fn validate_url_scheme_accepts_https() {
        assert!(validate_url_scheme("https://example.com/invoke").is_ok());
    }

    #[test]
    fn validate_url_scheme_rejects_file() {
        let err = validate_url_scheme("file:///etc/passwd").unwrap_err();
        assert!(matches!(err, InvokeError::InvalidScheme(_)));
        assert_eq!(err.error_code(), "invalid_scheme");
    }

    #[test]
    fn validate_url_scheme_rejects_ftp() {
        assert!(validate_url_scheme("ftp://evil.com/data").is_err());
    }

    #[test]
    fn validate_url_scheme_rejects_garbage() {
        assert!(validate_url_scheme("not-a-url").is_err());
    }

    #[test]
    fn redact_url_strips_query_and_userinfo() {
        let redacted = redact_url_for_log(
            "https://user:pass@api.example.com/invoke?api_key=secret&q=hello#frag", // pragma: allowlist secret
        );
        assert!(!redacted.contains("secret"));
        assert!(!redacted.contains("pass"));
        assert!(!redacted.contains("user"));
        assert!(!redacted.contains("frag"));
        assert!(redacted.contains("REDACTED"));
        assert!(redacted.contains("api.example.com/invoke"));
    }

    #[test]
    fn redact_url_no_query_unchanged() {
        let redacted = redact_url_for_log("https://api.example.com/invoke");
        assert_eq!(redacted, "https://api.example.com/invoke");
    }

    #[test]
    fn redact_url_invalid_returns_placeholder() {
        assert_eq!(redact_url_for_log("not a url"), "<invalid-url>");
    }

    #[test]
    fn build_header_map_valid() {
        let mut h = HashMap::new();
        h.insert("content-type".to_string(), "application/json".to_string());
        assert!(build_header_map(&h).is_ok());
    }

    #[test]
    fn build_header_map_rejects_bad_name() {
        let mut h = HashMap::new();
        h.insert("bad header".to_string(), "value".to_string());
        let err = build_header_map(&h).unwrap_err();
        assert!(matches!(err, InvokeError::InvalidHeader(_)));
    }

    #[test]
    fn build_header_map_rejects_bad_value() {
        let mut h = HashMap::new();
        h.insert("x-test".to_string(), "bad\r\nvalue".to_string());
        let err = build_header_map(&h).unwrap_err();
        assert!(matches!(err, InvokeError::InvalidHeader(_)));
    }

    #[tokio::test]
    async fn execute_invoke_rejects_when_circuit_is_open() {
        let config = RuntimeConfig {
            max_response_body_bytes: 1024,
            max_retries: 0,
            retry_backoff_ms: 1,
            ..RuntimeConfig::parse_from(["test-bin"])
        };
        let circuit = CircuitBreaker::new(1, Duration::from_secs(1), Some(8));
        circuit.record_failure("http://example.com", "scope");
        let metrics = MetricsCollector::new(Some(8));
        let ctx = InvokeContext {
            circuit: &circuit,
            metrics: &metrics,
            scope_id: "scope",
            agent_key: "agent",
        };

        let err = execute_invoke(
            &Client::new(),
            &config,
            "http://example.com",
            &HashMap::new(),
            &json!({}),
            Duration::from_millis(50),
            Some(&ctx),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, InvokeError::CircuitOpen));
    }

    #[tokio::test]
    async fn execute_invoke_retries_5xx_and_returns_final_success() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(503))
            .up_to_n_times(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
            .mount(&server)
            .await;

        let config = RuntimeConfig {
            max_response_body_bytes: 1024,
            max_retries: 1,
            retry_backoff_ms: 1,
            ..RuntimeConfig::parse_from(["test-bin"])
        };

        let result = execute_invoke(
            &Client::new(),
            &config,
            &server.uri(),
            &HashMap::new(),
            &json!({}),
            Duration::from_secs(1),
            None,
        )
        .await
        .unwrap();

        assert_eq!(result.status_code, 200);
        assert_eq!(result.json, Some(json!({"ok": true})));
    }

    #[tokio::test]
    async fn execute_invoke_enforces_body_size_via_header_and_bytes() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(
                ResponseTemplate::new(200)
                    .append_header("content-length", "10")
                    .set_body_string("0123456789"),
            )
            .up_to_n_times(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200).set_body_string("0123456789"))
            .mount(&server)
            .await;

        let config = RuntimeConfig {
            max_response_body_bytes: 5,
            max_retries: 0,
            retry_backoff_ms: 1,
            ..RuntimeConfig::parse_from(["test-bin"])
        };

        let err = execute_invoke(
            &Client::new(),
            &config,
            &server.uri(),
            &HashMap::new(),
            &json!({}),
            Duration::from_secs(1),
            None,
        )
        .await
        .unwrap_err();
        assert!(matches!(err, InvokeError::OversizedResponse { .. }));

        let err = execute_invoke(
            &Client::new(),
            &config,
            &server.uri(),
            &HashMap::new(),
            &json!({}),
            Duration::from_secs(1),
            None,
        )
        .await
        .unwrap_err();
        assert!(matches!(err, InvokeError::OversizedResponse { .. }));
    }

    #[tokio::test]
    async fn execute_invoke_records_failure_for_non_success_response() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(500).set_body_json(json!({"error": true})))
            .mount(&server)
            .await;

        let config = RuntimeConfig {
            max_response_body_bytes: 1024,
            max_retries: 0,
            retry_backoff_ms: 1,
            ..RuntimeConfig::parse_from(["test-bin"])
        };
        let circuit = CircuitBreaker::new(5, Duration::from_secs(1), Some(8));
        let metrics = MetricsCollector::new(Some(8));
        let ctx = InvokeContext {
            circuit: &circuit,
            metrics: &metrics,
            scope_id: "scope",
            agent_key: "agent",
        };

        let result = execute_invoke(
            &Client::new(),
            &config,
            &server.uri(),
            &HashMap::new(),
            &json!({}),
            Duration::from_secs(1),
            Some(&ctx),
        )
        .await
        .unwrap();

        assert_eq!(result.status_code, 500);
        assert_eq!(metrics.snapshot().failed_calls, 1);
    }
}
