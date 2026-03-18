// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! # A2A Service
//!
//! High-performance Agent-to-Agent (A2A) invocation. Exposes an HTTP API (Axum) for single and
//! batch invoke; performs auth decryption (when secret set), HTTP POST, retry, circuit breaker,
//! and per-agent metrics.

mod auth;
mod circuit;
mod errors;
mod eviction;
mod http;
mod invoker;
mod metrics;
mod queue;
pub mod server;

pub use crate::auth::{
    apply_invoke_auth, decrypt_auth, decrypt_map_values, AuthConfig, InvokeAuth,
};
pub use crate::errors::A2AError;
pub use crate::http::{InvokeRequestDto, InvokeResultDto, parse_requests_from_json, results_to_json};
pub use crate::invoker::{
    A2AInvokeRequest, A2AInvokeResult, A2AInvoker, A2AResponse, InvokerConfig,
};
pub use crate::metrics::{AgentMetrics, AggregateMetrics, MetricsCollector};
pub use crate::queue::{init_queue, shutdown_queue, try_submit_batch, QueueError};

use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};


static INVOKER: OnceLock<A2AInvoker> = OnceLock::new();
static INVOKER_CONFIG: OnceLock<InvokerConfig> = OnceLock::new();

/// Initialize the A2A invoker (concurrency and retry limits). Call once at startup.
/// First call wins; subsequent calls are no-ops.
pub fn init_invoker(max_concurrent: usize, max_retries: u32) {
    let _ = INVOKER_CONFIG.get_or_init(|| {
        let mut config = InvokerConfig::default();
        config.max_concurrent = Some(max_concurrent);
        config.max_retries = max_retries;
        config
    });
}

/// Used by the queue worker to run HTTP. Not part of the public API.
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

/// Submit a batch of requests (from JSON DTOs) and wait for results.
/// Returns JSON-serializable result DTOs. Call after `init_queue` and optionally `init_invoker`.
pub async fn submit_batch(
    requests: &[InvokeRequestDto],
    auth_secret: Option<&str>,
    timeout_secs: f64,
) -> Result<Vec<InvokeResultDto>, BatchSubmitError> {
    let rust_requests = parse_requests_from_json(requests, auth_secret).map_err(BatchSubmitError::Parse)?;
    let timeout = Duration::from_secs_f64(timeout_secs);
    let rx = try_submit_batch(rust_requests, timeout).map_err(BatchSubmitError::Queue)?;
    let results = rx.await.map_err(|_| BatchSubmitError::Queue(QueueError::Shutdown))?;
    let end_time_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    Ok(results_to_json(results, end_time_secs))
}

/// Error when submitting a batch via HTTP API.
#[derive(Debug)]
pub enum BatchSubmitError {
    Parse(A2AError),
    Queue(QueueError),
}

impl std::fmt::Display for BatchSubmitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BatchSubmitError::Parse(e) => write!(f, "parse: {}", e),
            BatchSubmitError::Queue(e) => write!(f, "queue: {:?}", e),
        }
    }
}

impl std::error::Error for BatchSubmitError {}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::auth::apply_invoke_auth;
    use crate::auth::InvokeAuth;
    use crate::errors::A2AError;
    use crate::queue::QueueError;
    use crate::BatchSubmitError;

    #[test]
    fn test_batch_submit_error_display() {
        let e = BatchSubmitError::Parse(A2AError::Auth("bad".to_string()));
        assert!(e.to_string().contains("parse"));
        let e2 = BatchSubmitError::Queue(QueueError::Full);
        assert!(e2.to_string().contains("Full"));
    }

    #[test]
    fn test_apply_invoke_auth_injects_traceparent() {
        let mut headers = HashMap::new();
        headers.insert("X-Test".to_string(), "1".to_string());
        let traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
        let auth = InvokeAuth {
            query_params: None,
            headers: {
                let mut h = headers;
                h.insert("traceparent".to_string(), traceparent.to_string());
                h
            },
        };
        let (url, out_headers) = apply_invoke_auth("https://example.com", &auth).unwrap();
        assert!(url == "https://example.com" || url == "https://example.com/");
        assert_eq!(out_headers.get("traceparent").map(String::as_str), Some(traceparent));
        assert_eq!(out_headers.get("X-Test").map(String::as_str), Some("1"));
    }
}
