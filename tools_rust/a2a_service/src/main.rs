// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! A2A invoke service: standalone Axum HTTP server for single and batch agent invocation.

use std::sync::Arc;

use clap::Parser;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use a2a_service::{init_invoker, init_queue, server};

mod config;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = config::Config::parse();
    let listen = config
        .listen_socket_addr()
        .map_err(|e| format!("invalid listen address: {}", e))?;

    init_invoker(config.max_concurrent, 1);
    init_queue(
        config.max_concurrent,
        config.max_queued,
        config.auth_secret.clone(),
    );

    let state = server::AppState {
        auth_secret: config.auth_secret.clone(),
        timeout_secs: config.invoke_timeout_secs,
        backend_base_url: config.backend_base_url.trim_end_matches('/').to_string(),
        client: reqwest::Client::new(),
    };

    let app = server::router(Arc::new(state));

    info!("A2A service listening on http://{}", listen);
    let listener = tokio::net::TcpListener::bind(listen).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
