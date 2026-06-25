// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::middleware::{Next, from_fn_with_state};
use axum::response::{IntoResponse, Response};
use axum::serve::ListenerExt;
use rmcp::transport::streamable_http_server::StreamableHttpService;
use rmcp::transport::streamable_http_server::session::local::LocalSessionManager;
use serde_json::json;
use std::env;
use std::sync::Arc;
use tracing::info;
use tracing::trace;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::config::{
    APP_NAME, APP_VERSION, DEFAULT_BIND_ADDRESS, MAX_ACTIVE_SESSIONS, MCP_PROTOCOL_VERSION,
    SESSION_HEADER,
};
use crate::rest;
use crate::server::FastTimeServer;
use crate::transports::sse;

pub async fn run() -> anyhow::Result<()> {
    init_logging();

    let bind_address =
        env::var("BIND_ADDRESS").unwrap_or_else(|_| DEFAULT_BIND_ADDRESS.to_string());

    info!("{} v{} starting...", APP_NAME, APP_VERSION);
    info!("Binding to: {}", bind_address);

    let tcp_listener = tokio::net::TcpListener::bind(&bind_address)
        .await?
        .tap_io(|tcp_stream| {
            if let Err(err) = tcp_stream.set_nodelay(true) {
                trace!("failed to set TCP_NODELAY on incoming connection: {err:#}");
            }
        });

    info!("MCP endpoint:   http://{}/mcp", bind_address);
    info!("MCP SSE:        http://{}/sse", bind_address);
    info!(
        "REST API:       http://{}/api/echo (POST), /api/time (GET)",
        bind_address
    );
    info!("Health check:   http://{}/health", bind_address);
    info!("Version info:   http://{}/version", bind_address);
    info!("");
    info!("Benchmark with:");
    info!("  hey -n 1000000 -c 200 -m POST -T 'application/json' \\");
    info!(
        "      -d '{{\"message\":\"hello\"}}' http://{}/api/echo",
        bind_address
    );

    axum::serve(tcp_listener, router())
        .with_graceful_shutdown(async move {
            tokio::signal::ctrl_c().await.unwrap();
            info!("Shutting down...");
        })
        .await?;

    Ok(())
}

fn init_logging() {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".to_string().into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();
}

fn router() -> Router {
    // Modern Streamable HTTP transport, served by the rmcp SDK. We hold a handle
    // to the session manager so a lightweight gate can cap concurrent sessions —
    // rmcp's LocalSessionManager has no built-in cap. Existing sessions are
    // cleaned up by rmcp on client disconnect / HTTP DELETE.
    let session_manager: Arc<LocalSessionManager> = Arc::new(LocalSessionManager::default());
    let mcp = StreamableHttpService::new(
        || Ok(FastTimeServer::new()),
        session_manager.clone(),
        Default::default(),
    );
    let mcp = Router::new()
        .fallback_service(mcp)
        .layer(from_fn_with_state(session_manager, session_cap_gate));

    Router::new()
        .route("/health", axum::routing::get(health_handler))
        .route("/version", axum::routing::get(version_handler))
        .route("/api/echo", axum::routing::post(rest::echo_handler))
        .route("/api/time", axum::routing::get(rest::time_handler))
        // Legacy HTTP+SSE transport — hand-rolled shim (see transports/sse.rs).
        .route("/sse", axum::routing::get(sse::handler))
        .route("/messages", axum::routing::post(sse::message_handler))
        .route("/message", axum::routing::post(sse::message_handler))
        .nest("/mcp", mcp)
}

/// Cap concurrent Streamable HTTP sessions at `MAX_ACTIVE_SESSIONS`. Requests
/// carrying an existing `mcp-session-id` always pass so in-flight sessions keep
/// working; only session-creating requests (no session header) are rejected
/// with `503` once the cap is reached.
async fn session_cap_gate(
    State(session_manager): State<Arc<LocalSessionManager>>,
    request: Request,
    next: Next,
) -> Response {
    let creates_new_session = !request.headers().contains_key(SESSION_HEADER);
    if creates_new_session && session_manager.sessions.read().await.len() >= MAX_ACTIVE_SESSIONS {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "Maximum active sessions reached",
        )
            .into_response();
    }
    next.run(request).await
}

async fn health_handler() -> axum::Json<serde_json::Value> {
    axum::Json(json!({
        "status": "healthy",
        "server": APP_NAME,
        "version": APP_VERSION
    }))
}

async fn version_handler() -> axum::Json<serde_json::Value> {
    axum::Json(json!({
        "name": APP_NAME,
        "version": APP_VERSION,
        "mcp_version": MCP_PROTOCOL_VERSION
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_version_endpoint_advertises_latest_protocol() {
        let version = version_handler().await;
        assert_eq!(version.0["mcp_version"], MCP_PROTOCOL_VERSION);
    }
}
