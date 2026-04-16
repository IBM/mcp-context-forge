// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Webhook dispatch module for A2A push notification configs.
//!
//! Queries the Python backend for registered push configs, then
//! fire-and-forgets a POST to each matching webhook URL.  Errors are
//! logged but never propagated to the caller.

use crate::metrics::MetricsCollector;
use crate::trust::{build_trust_headers, reqwest_headers};
use reqwest::Client;
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};

/// A single push notification configuration returned by the Python backend.
#[derive(Debug, Deserialize)]
struct PushConfig {
    webhook_url: String,
    auth_token: Option<String>,
    events: Option<Vec<String>>,
    enabled: bool,
}

/// Envelope shape returned by `/_internal/a2a/push/list`.
///
/// The Python endpoint wraps the visible configs in ``{"configs": [...]}``
/// so that future fields (pagination cursors, error summaries) can be added
/// without a breaking change.
#[derive(Debug, Deserialize)]
struct PushConfigList {
    configs: Vec<PushConfig>,
}

/// Check if a push config should fire for the given state change.
fn should_dispatch(config: &PushConfig, new_state: &str) -> bool {
    if !config.enabled {
        return false;
    }
    match &config.events {
        Some(events) => events.iter().any(|e| e.eq_ignore_ascii_case(new_state)),
        None => true,
    }
}

/// Fetch all push configs for a task/agent pair and dispatch matching webhooks.
///
/// Calls `POST {backend_base_url}/_internal/a2a/push/list` with trust headers
/// to obtain the list of [`PushConfig`] entries.  For each config that is
/// `enabled` and whose `events` list contains `new_state` (or has no `events`
/// filter at all), a fire-and-forget [`tokio::spawn`] task is launched to POST
/// `task_payload` to the `webhook_url` with up to 3 attempts and exponential
/// backoff starting at 1 s.
///
/// All errors are logged; none are returned.
#[allow(clippy::too_many_arguments)]
pub async fn dispatch_webhooks(
    client: &Client,
    backend_base_url: &str,
    auth_secret: &str, // pragma: allowlist secret
    task_id: &str,
    agent_id: &str,
    new_state: &str,
    task_payload: &Value,
    metrics: Arc<MetricsCollector>,
) {
    let list_url = format!(
        "{}/_internal/a2a/push/list",
        backend_base_url.trim_end_matches('/')
    );

    let trust_headers = build_trust_headers(auth_secret);
    let body = json!({ "task_id": task_id, "agent_id": agent_id });

    let response = match client
        .post(&list_url)
        .headers(reqwest_headers(&trust_headers))
        .json(&body)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            error!(
                error = %e,
                task_id,
                agent_id,
                "failed to contact push/list endpoint"
            );
            metrics.record_webhook_list_aborted();
            return;
        }
    };

    let status = response.status().as_u16();
    if status != 200 {
        let detail = response.text().await.unwrap_or_default();
        error!(
            status,
            task_id,
            agent_id,
            detail = %detail,
            "push/list returned non-200"
        );
        metrics.record_webhook_list_aborted();
        return;
    }

    let configs: Vec<PushConfig> = match response.json::<PushConfigList>().await {
        Ok(envelope) => envelope.configs,
        Err(e) => {
            error!(
                error = %e,
                task_id,
                agent_id,
                "failed to deserialize push/list response"
            );
            metrics.record_webhook_list_aborted();
            return;
        }
    };

    for config in configs {
        if !should_dispatch(&config, new_state) {
            continue;
        }

        let webhook_url = config.webhook_url.clone();
        let auth_token = config.auth_token.clone();
        let payload = task_payload.clone();
        let client_clone = client.clone();
        let metrics_clone = Arc::clone(&metrics);

        info!(
            webhook_url = %webhook_url,
            task_id,
            agent_id,
            new_state,
            "dispatching push notification"
        );

        tokio::spawn(async move {
            const MAX_ATTEMPTS: u32 = 3;
            let backoff_base = Duration::from_secs(1);

            for attempt in 0..MAX_ATTEMPTS {
                if attempt > 0 {
                    let delay = backoff_base * 2u32.saturating_pow(attempt - 1);
                    warn!(
                        attempt,
                        backoff_ms = delay.as_millis() as u64,
                        webhook_url = %webhook_url,
                        "retrying webhook dispatch"
                    );
                    tokio::time::sleep(delay).await;
                }

                let mut req = client_clone.post(&webhook_url).json(&payload);

                if let Some(ref token) = auth_token {
                    req = req.bearer_auth(token);
                }

                match req.send().await {
                    Ok(resp) => {
                        let status = resp.status().as_u16();
                        if (200..300).contains(&status) {
                            info!(
                                status,
                                webhook_url = %webhook_url,
                                attempt,
                                "webhook dispatch succeeded"
                            );
                            return;
                        }
                        let detail = resp.text().await.unwrap_or_default();
                        warn!(
                            status,
                            webhook_url = %webhook_url,
                            attempt,
                            detail = %detail,
                            "webhook returned non-2xx"
                        );
                        // 4xx responses are not retried — the config or payload is wrong.
                        if (400..500).contains(&status) {
                            error!(
                                status,
                                webhook_url = %webhook_url,
                                "webhook dispatch permanently failed (4xx)"
                            );
                            metrics_clone.record_webhook_permanent_failure();
                            return;
                        }
                    }
                    Err(e) => {
                        warn!(
                            error = %e,
                            webhook_url = %webhook_url,
                            attempt,
                            "webhook dispatch network error"
                        );
                    }
                }
            }

            error!(
                webhook_url = %webhook_url,
                "webhook dispatch exhausted all retries"
            );
            metrics_clone.record_webhook_retry_exhausted();
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn push_config_deserializes_from_json() {
        let json = r#"{
            "webhook_url": "https://example.com/hook",
            "auth_token": "secret-token",
            "events": ["completed", "failed"],
            "enabled": true
        }"#;
        let config: PushConfig = serde_json::from_str(json).expect("deserialization failed");
        assert_eq!(config.webhook_url, "https://example.com/hook");
        assert_eq!(config.auth_token.as_deref(), Some("secret-token"));
        assert_eq!(
            config.events.as_deref(),
            Some(vec!["completed".to_string(), "failed".to_string()].as_slice())
        );
        assert!(config.enabled);
    }

    #[test]
    fn push_config_deserializes_with_null_fields() {
        let json = r#"{
            "webhook_url": "https://example.com/hook",
            "auth_token": null,
            "events": null,
            "enabled": true
        }"#;
        let config: PushConfig = serde_json::from_str(json).expect("deserialization failed");
        assert!(config.auth_token.is_none());
        assert!(config.events.is_none());
    }

    #[test]
    fn push_config_events_filter_matches() {
        let config = PushConfig {
            webhook_url: "https://example.com/hook".to_string(),
            auth_token: None,
            events: Some(vec!["completed".to_string(), "failed".to_string()]),
            enabled: true,
        };
        assert!(should_dispatch(&config, "completed"));
        assert!(should_dispatch(&config, "COMPLETED")); // case-insensitive
        assert!(should_dispatch(&config, "failed"));
        assert!(!should_dispatch(&config, "working"));
    }

    #[test]
    fn push_config_disabled_is_skipped() {
        let config = PushConfig {
            webhook_url: "https://example.com/hook".to_string(),
            auth_token: None,
            events: None,
            enabled: false,
        };
        assert!(!should_dispatch(&config, "completed"));
        assert!(!should_dispatch(&config, "working"));
    }

    #[test]
    fn push_config_no_events_filter_matches_all() {
        let config = PushConfig {
            webhook_url: "https://example.com/hook".to_string(),
            auth_token: None,
            events: None,
            enabled: true,
        };
        assert!(should_dispatch(&config, "completed"));
        assert!(should_dispatch(&config, "working"));
        assert!(should_dispatch(&config, "failed"));
        assert!(should_dispatch(&config, "any-arbitrary-state"));
    }

    #[tokio::test]
    async fn dispatch_webhooks_returns_when_push_list_fails() {
        dispatch_webhooks(
            &Client::new(),
            "http://127.0.0.1:1",
            "secret",
            "task-1",
            "agent-1",
            "completed",
            &json!({"task_id": "task-1"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;
    }

    #[tokio::test]
    async fn dispatch_webhooks_ignores_non_200_and_bad_json_list_responses() {
        let client = Client::new();
        let non_200_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(500))
            .expect(1)
            .mount(&non_200_server)
            .await;

        dispatch_webhooks(
            &client,
            &non_200_server.uri(),
            "secret",
            "task-2",
            "agent-2",
            "completed",
            &json!({"task_id": "task-2"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;

        non_200_server.verify().await;

        let bad_json_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_raw("not-json", "application/json"))
            .expect(1)
            .mount(&bad_json_server)
            .await;

        dispatch_webhooks(
            &client,
            &bad_json_server.uri(),
            "secret",
            "task-3",
            "agent-3",
            "completed",
            &json!({"task_id": "task-3"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;

        bad_json_server.verify().await;
    }

    #[tokio::test]
    async fn dispatch_webhooks_sends_matching_webhook_with_bearer_token() {
        let mock_server = MockServer::start().await;
        let client = Client::new();

        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "configs": [
                    {
                        "webhook_url": format!("{}/hook", mock_server.uri()),
                        "auth_token": "secret-token",
                        "events": ["completed"],
                        "enabled": true
                    }
                ]
            })))
            .expect(1)
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/hook"))
            .and(header("authorization", "Bearer secret-token"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&mock_server)
            .await;

        dispatch_webhooks(
            &client,
            &mock_server.uri(),
            "secret",
            "task-4",
            "agent-4",
            "completed",
            &json!({"task_id": "task-4", "state": "completed"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;

        tokio::time::sleep(Duration::from_millis(50)).await;
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn dispatch_webhooks_sends_matching_webhook_without_authorization_when_token_is_null() {
        let mock_server = MockServer::start().await;
        let client = Client::new();

        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "configs": [
                    {
                        "webhook_url": format!("{}/hook-no-auth", mock_server.uri()),
                        "auth_token": null,
                        "events": ["completed"],
                        "enabled": true
                    }
                ]
            })))
            .expect(1)
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/hook-no-auth"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&mock_server)
            .await;

        dispatch_webhooks(
            &client,
            &mock_server.uri(),
            "secret",
            "task-4b",
            "agent-4b",
            "completed",
            &json!({"task_id": "task-4b", "state": "completed"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;

        tokio::time::sleep(Duration::from_millis(50)).await;
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn dispatch_webhooks_skips_non_matching_configs_and_does_not_retry_4xx() {
        let mock_server = MockServer::start().await;
        let client = Client::new();

        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "configs": [
                    {
                        "webhook_url": format!("{}/skip", mock_server.uri()),
                        "auth_token": null,
                        "events": ["failed"],
                        "enabled": true
                    },
                    {
                        "webhook_url": format!("{}/fail-once", mock_server.uri()),
                        "auth_token": null,
                        "events": ["completed"],
                        "enabled": true
                    }
                ]
            })))
            .expect(1)
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/skip"))
            .respond_with(ResponseTemplate::new(204))
            .expect(0)
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/fail-once"))
            .respond_with(ResponseTemplate::new(400))
            .expect(1)
            .mount(&mock_server)
            .await;

        dispatch_webhooks(
            &client,
            &mock_server.uri(),
            "secret",
            "task-5",
            "agent-5",
            "completed",
            &json!({"task_id": "task-5", "state": "completed"}),
            Arc::new(MetricsCollector::new(None)),
        )
        .await;

        tokio::time::sleep(Duration::from_millis(50)).await;
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn dispatch_webhooks_increments_list_aborted_on_network_failure() {
        let metrics = Arc::new(MetricsCollector::new(None));
        assert_eq!(metrics.webhook_list_aborted_count(), 0);

        dispatch_webhooks(
            &Client::new(),
            "http://127.0.0.1:1", // non-listening port
            "secret",
            "task-a",
            "agent-a",
            "completed",
            &json!({"task_id": "task-a"}),
            Arc::clone(&metrics),
        )
        .await;

        assert_eq!(
            metrics.webhook_list_aborted_count(),
            1,
            "list-unreachable must increment webhook_list_aborted"
        );
    }

    #[tokio::test]
    async fn dispatch_webhooks_increments_list_aborted_on_non_200() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(500))
            .mount(&mock_server)
            .await;

        let metrics = Arc::new(MetricsCollector::new(None));
        dispatch_webhooks(
            &Client::new(),
            &mock_server.uri(),
            "secret",
            "task-b",
            "agent-b",
            "completed",
            &json!({"task_id": "task-b"}),
            Arc::clone(&metrics),
        )
        .await;
        assert_eq!(metrics.webhook_list_aborted_count(), 1);
    }

    #[tokio::test]
    async fn dispatch_webhooks_increments_list_aborted_on_bad_json() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_raw("not-json", "application/json"))
            .mount(&mock_server)
            .await;

        let metrics = Arc::new(MetricsCollector::new(None));
        dispatch_webhooks(
            &Client::new(),
            &mock_server.uri(),
            "secret",
            "task-c",
            "agent-c",
            "completed",
            &json!({"task_id": "task-c"}),
            Arc::clone(&metrics),
        )
        .await;
        assert_eq!(metrics.webhook_list_aborted_count(), 1);
    }

    #[tokio::test]
    async fn dispatch_webhooks_increments_permanent_failure_on_4xx() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "configs": [
                    {
                        "webhook_url": format!("{}/bad-req", mock_server.uri()),
                        "auth_token": null,
                        "events": ["completed"],
                        "enabled": true
                    }
                ]
            })))
            .mount(&mock_server)
            .await;
        Mock::given(method("POST"))
            .and(path("/bad-req"))
            .respond_with(ResponseTemplate::new(401))
            .mount(&mock_server)
            .await;

        let metrics = Arc::new(MetricsCollector::new(None));
        dispatch_webhooks(
            &Client::new(),
            &mock_server.uri(),
            "secret",
            "task-d",
            "agent-d",
            "completed",
            &json!({"task_id": "task-d"}),
            Arc::clone(&metrics),
        )
        .await;

        // Dispatch is spawned; wait for the single attempt.
        for _ in 0..20 {
            if metrics.webhook_permanent_failure_count() >= 1 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        assert_eq!(metrics.webhook_permanent_failure_count(), 1);
        assert_eq!(
            metrics.webhook_retry_exhausted_count(),
            0,
            "4xx must not double-count as retry-exhausted"
        );
    }

    #[tokio::test]
    async fn dispatch_webhooks_increments_metric_on_retry_exhaustion() {
        // 5xx that survives all retries; assert the metric counter moved.
        let mock_server = MockServer::start().await;
        let client = Client::new();

        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/list"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "configs": [
                    {
                        "webhook_url": format!("{}/persistent-5xx", mock_server.uri()),
                        "auth_token": null,
                        "events": ["completed"],
                        "enabled": true
                    }
                ]
            })))
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/persistent-5xx"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&mock_server)
            .await;

        let metrics = Arc::new(MetricsCollector::new(None));
        assert_eq!(metrics.webhook_retry_exhausted_count(), 0);

        dispatch_webhooks(
            &client,
            &mock_server.uri(),
            "secret",
            "task-6",
            "agent-6",
            "completed",
            &json!({"task_id": "task-6"}),
            Arc::clone(&metrics),
        )
        .await;

        // Dispatch is spawned; wait for the retry loop to exhaust.
        // Retries: attempt 0 (immediate) + 1s + 2s backoff ≈ 3s total.
        for _ in 0..40 {
            if metrics.webhook_retry_exhausted_count() >= 1 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        assert_eq!(metrics.webhook_retry_exhausted_count(), 1);
    }
}
