// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Webhook dispatch module for A2A push notification configs.
//!
//! Queries the Python backend for registered push configs, then
//! fire-and-forgets a POST to each matching webhook URL.  Errors are
//! logged but never propagated to the caller.

use crate::trust::{build_trust_headers, reqwest_headers};
use reqwest::Client;
use serde::Deserialize;
use serde_json::{Value, json};
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
pub async fn dispatch_webhooks(
    client: &Client,
    backend_base_url: &str,
    auth_secret: &str,
    task_id: &str,
    agent_id: &str,
    new_state: &str,
    task_payload: &Value,
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
        return;
    }

    let configs: Vec<PushConfig> = match response.json().await {
        Ok(c) => c,
        Err(e) => {
            error!(
                error = %e,
                task_id,
                agent_id,
                "failed to deserialize push/list response"
            );
            return;
        }
    };

    for config in configs {
        if !config.enabled {
            continue;
        }

        // If the config has an events filter, the current state must be listed.
        if let Some(ref events) = config.events {
            if !events.iter().any(|e| e == new_state) {
                continue;
            }
        }

        let webhook_url = config.webhook_url.clone();
        let auth_token = config.auth_token.clone();
        let payload = task_payload.clone();
        let client_clone = client.clone();

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
        });
    }
}
