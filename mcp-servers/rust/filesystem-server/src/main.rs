use anyhow::{Context, Result};
use rmcp::transport;
use tracing_subscriber::EnvFilter;
mod server;
mod tools;
use crate::server::{AppContext, FilesystemServer};
use clap::Parser;
mod sandbox;
use sandbox::Sandbox;
use std::sync::Arc;

pub fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new("INFO"))
        .with_ansi(true)
        .try_init();
}

#[derive(Parser, Debug)]
struct Args {
    #[arg(long)]
    roots: Vec<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    init_tracing();
    tracing::info!("---- Starting Filesystem MCP Server ----");
    tracing::info!("Using root folders: {:?}", &args.roots);

    // Initialize sandbox once
    let sandbox = Arc::new(
        Sandbox::new(args.roots)
            .await
            .context("Could not add roots")?,
    );
    let ctx = Arc::new(AppContext { sandbox });

    // Streamable HTTP service
    // Clone ctx inside closure so each server instance gets its own Arc
    let service = transport::streamable_http_server::StreamableHttpService::new(
        {
            let ctx = ctx.clone();
            move || Ok(FilesystemServer::new(ctx.clone()))
        },
        transport::streamable_http_server::session::local::LocalSessionManager::default().into(),
        Default::default(),
    );

    // Create router
    let router = axum::Router::new().nest_service("/mcp", service.clone());

    // Bind to TCP listener
    let listener = tokio::net::TcpListener::bind("127.0.0.1:8084")
        .await
        .context("Failed to bind to port")?;

    tracing::info!("Server listening on http://127.0.0.1:8084/mcp");

    // Serve
    axum::serve(listener, router)
        .await
        .context("Server error")?;

    Ok(())
}
