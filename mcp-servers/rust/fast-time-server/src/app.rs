// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::Router;
use axum::extract::{Request, State};
use axum::http::{StatusCode, header};
use axum::middleware::{Next, from_fn_with_state};
use axum::response::{IntoResponse, Response};
use axum::serve::ListenerExt;
use clap::Parser;
use rmcp::ServiceExt;
use rmcp::transport::streamable_http_server::StreamableHttpService;
use rmcp::transport::streamable_http_server::session::local::LocalSessionManager;
use serde_json::json;
use std::sync::Arc;
use tracing::info;
use tracing::trace;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::cli::{Cli, Transport};
use crate::config::{
    APP_NAME, APP_VERSION, MAX_ACTIVE_SESSIONS, MCP_PROTOCOL_VERSION, SESSION_HEADER,
};
use crate::rest;
use crate::rest_v1;
use crate::server::FastTimeServer;
use crate::transports::sse;

pub async fn run() -> anyhow::Result<()> {
    let cli = Cli::parse();
    init_logging(cli.log_directive());

    match cli.transport {
        Transport::Stdio => serve_stdio().await,
        Transport::Sse | Transport::Http | Transport::Dual | Transport::Rest => {
            serve_http(&cli).await
        }
    }
}

/// Serve MCP over stdin/stdout (`--transport stdio`).
async fn serve_stdio() -> anyhow::Result<()> {
    info!("{} v{} serving via stdio transport", APP_NAME, APP_VERSION);
    let service = FastTimeServer::new()
        .serve(rmcp::transport::stdio())
        .await?;
    service.waiting().await?;
    Ok(())
}

/// Serve the full HTTP router (every route) on the resolved address.
async fn serve_http(cli: &Cli) -> anyhow::Result<()> {
    let bind_address = cli.effective_addr();
    let auth_token = cli.auth_token();

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
    info!("MCP HTTP alias: http://{}/http", bind_address);
    info!("MCP SSE:        http://{}/sse", bind_address);
    info!(
        "REST API:       http://{}/api/v1/time (GET), /api/v1/convert (POST)",
        bind_address
    );
    info!("Health check:   http://{}/health", bind_address);
    info!("Version info:   http://{}/version", bind_address);
    if auth_token.is_some() {
        info!("Auth:           Bearer token required (except /health, /version)");
    }
    if !cli.public_url.is_empty() {
        info!("Public URL:     {}", cli.public_url);
    }

    axum::serve(tcp_listener, router(auth_token))
        .with_graceful_shutdown(async move {
            tokio::signal::ctrl_c().await.unwrap();
            info!("Shutting down...");
        })
        .await?;

    Ok(())
}

fn init_logging(directive: &str) {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| directive.into()),
        )
        // Log to stderr so the stdio transport keeps stdout as a pure JSON-RPC
        // stream; harmless for the HTTP transports.
        .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
        .init();
}

/// Reject requests without a valid `Authorization: Bearer <token>` header.
/// `/health` and `/version` are always exempt so health checks keep working.
async fn auth_gate(State(token): State<Arc<String>>, request: Request, next: Next) -> Response {
    let path = request.uri().path();
    if path == "/health" || path == "/version" {
        return next.run(request).await;
    }
    let header_value = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok());
    match header_value {
        None => (
            StatusCode::UNAUTHORIZED,
            [(header::WWW_AUTHENTICATE, "Bearer realm=\"MCP Server\"")],
            "Authorization required",
        )
            .into_response(),
        Some(value) if value.strip_prefix("Bearer ") != Some(token.as_str()) => {
            let message = if value.starts_with("Bearer ") {
                "Invalid token"
            } else {
                "Invalid authorization format"
            };
            (StatusCode::UNAUTHORIZED, message).into_response()
        }
        Some(_) => next.run(request).await,
    }
}

fn router(auth_token: Option<String>) -> Router {
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

    let app = Router::new()
        .route("/health", axum::routing::get(health_handler))
        .route("/version", axum::routing::get(version_handler))
        // High-throughput benchmark endpoints (Rust-specific).
        .route("/api/echo", axum::routing::post(rest::echo_handler))
        .route("/api/time", axum::routing::get(rest::time_handler))
        // Full Go-parity REST surface.
        .merge(rest_v1::routes())
        // Legacy HTTP+SSE transport — hand-rolled shim (see transports/sse.rs).
        .route("/sse", axum::routing::get(sse::handler))
        .route("/messages", axum::routing::post(sse::message_handler))
        .route("/message", axum::routing::post(sse::message_handler))
        .nest("/http", mcp.clone())
        .nest("/mcp", mcp);

    let app = match auth_token {
        Some(token) => app.layer(from_fn_with_state(Arc::new(token), auth_gate)),
        None => app,
    };
    // CORS is the outermost layer so preflight OPTIONS is answered without auth.
    app.layer(axum::middleware::from_fn(rest_v1::cors))
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
