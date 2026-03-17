// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Experimental Rust A2A runtime sidecar for ContextForge.

pub mod config;

use axum::{
    Json, Router,
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode},
    routing::{get, post},
};
use config::{ListenTarget, RuntimeConfig};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use thiserror::Error;
use tracing::info;

const RUNTIME_NAME: &str = "contextforge-a2a-runtime";

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("{0}")]
    Config(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    HttpClient(#[from] reqwest::Error),
}

#[derive(Clone)]
struct AppState {
    config: Arc<RuntimeConfig>,
    client: Client,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    runtime: &'static str,
    listen_http: String,
    listen_uds: Option<String>,
}

#[derive(Debug, Deserialize)]
struct InvokeRequest {
    endpoint_url: String,
    #[serde(default)]
    headers: HashMap<String, String>,
    json_body: Value,
    timeout_seconds: Option<u64>,
}

#[derive(Debug, Serialize)]
struct InvokeResponse {
    status_code: u16,
    headers: HashMap<String, String>,
    json: Option<Value>,
    text: String,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
}

pub async fn run(config: RuntimeConfig) -> Result<(), RuntimeError> {
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_millis(config.client_connect_timeout_ms))
        .pool_idle_timeout(Duration::from_secs(config.client_pool_idle_timeout_seconds))
        .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
        .tcp_keepalive(Duration::from_secs(config.client_tcp_keepalive_seconds))
        .timeout(Duration::from_millis(config.request_timeout_ms))
        .build()?;

    let state = AppState {
        config: Arc::new(config.clone()),
        client,
    };
    let app = Router::new()
        .route("/health", get(health))
        .route("/healthz", get(health))
        .route("/invoke", post(invoke))
        .with_state(state);
    let shutdown_after = config.exit_after_startup_ms.map(Duration::from_millis);

    match config.listen_target().map_err(RuntimeError::Config)? {
        ListenTarget::Http(addr) => serve_http(app, addr, shutdown_after).await?,
        ListenTarget::Uds(path) => serve_uds(app, path, shutdown_after).await?,
    }

    Ok(())
}

async fn serve_http(
    app: Router,
    addr: std::net::SocketAddr,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    info!("starting Rust A2A runtime on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
    }
    Ok(())
}

async fn serve_uds(
    app: Router,
    path: PathBuf,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    if Path::new(&path).exists() {
        std::fs::remove_file(&path)?;
    }
    info!("starting Rust A2A runtime on unix://{}", path.display());
    let listener = tokio::net::UnixListener::bind(&path)?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
    }
    Ok(())
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        runtime: RUNTIME_NAME,
        listen_http: state.config.listen_http.clone(),
        listen_uds: state
            .config
            .listen_uds
            .as_ref()
            .map(|path| path.display().to_string()),
    })
}

async fn invoke(
    State(state): State<AppState>,
    Json(request): Json<InvokeRequest>,
) -> Result<Json<InvokeResponse>, (StatusCode, Json<ErrorResponse>)> {
    let timeout = request
        .timeout_seconds
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_millis(state.config.request_timeout_ms));
    let headers = build_header_map(&request.headers).map_err(|err| {
        (
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: err.to_string(),
            }),
        )
    })?;

    let response = state
        .client
        .post(&request.endpoint_url)
        .headers(headers)
        .json(&request.json_body)
        .timeout(timeout)
        .send()
        .await
        .map_err(|err| {
            let status = if err.is_timeout() {
                StatusCode::GATEWAY_TIMEOUT
            } else {
                StatusCode::BAD_GATEWAY
            };
            (
                status,
                Json(ErrorResponse {
                    error: err.to_string(),
                }),
            )
        })?;

    let status_code = response.status().as_u16();
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
    let bytes = response.bytes().await.map_err(|err| {
        (
            StatusCode::BAD_GATEWAY,
            Json(ErrorResponse {
                error: err.to_string(),
            }),
        )
    })?;
    let json = serde_json::from_slice::<Value>(&bytes).ok();
    let text = String::from_utf8_lossy(&bytes).to_string();

    Ok(Json(InvokeResponse {
        status_code,
        headers: response_headers,
        json,
        text,
    }))
}

fn build_header_map(headers: &HashMap<String, String>) -> Result<HeaderMap, RuntimeError> {
    let mut header_map = HeaderMap::new();
    for (name, value) in headers {
        let header_name = HeaderName::from_bytes(name.as_bytes()).map_err(|err| {
            RuntimeError::Config(format!("invalid outbound header name '{name}': {err}"))
        })?;
        let header_value = HeaderValue::from_str(value).map_err(|err| {
            RuntimeError::Config(format!("invalid outbound header value for '{name}': {err}"))
        })?;
        header_map.insert(header_name, header_value);
    }
    Ok(header_map)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_header_map_accepts_valid_headers() {
        let headers = HashMap::from([
            ("content-type".to_string(), "application/json".to_string()),
            ("a2a-version".to_string(), "1.0".to_string()),
        ]);

        let header_map = build_header_map(&headers).expect("header map");
        assert_eq!(
            header_map
                .get("content-type")
                .and_then(|value| value.to_str().ok()),
            Some("application/json")
        );
    }

    #[test]
    fn build_header_map_rejects_invalid_header_name() {
        let headers = HashMap::from([("bad header".to_string(), "value".to_string())]);
        let err = build_header_map(&headers).expect_err("invalid header should fail");
        assert!(err.to_string().contains("invalid outbound header name"));
    }
}
