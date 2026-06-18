// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::Router;
use axum::serve::ListenerExt;
use serde_json::json;
use std::env;
use tracing::info;
use tracing::trace;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::config::{APP_NAME, APP_VERSION, DEFAULT_BIND_ADDRESS, MCP_PROTOCOL_VERSION};
use crate::rest;
use crate::transports::{sse, streamable_http};

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
    Router::new()
        .route("/health", axum::routing::get(health_handler))
        .route("/version", axum::routing::get(version_handler))
        .route("/api/echo", axum::routing::post(rest::echo_handler))
        .route("/api/time", axum::routing::get(rest::time_handler))
        .route(
            "/mcp",
            axum::routing::post(streamable_http::handler).delete(streamable_http::delete_handler),
        )
        .route("/sse", axum::routing::get(sse::handler))
        .route("/messages", axum::routing::post(sse::message_handler))
        .route("/message", axum::routing::post(sse::message_handler))
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
