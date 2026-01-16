use anyhow::{Context, Result};
use rmcp::transport;
use tracing_subscriber::EnvFilter;
mod server;
mod tools;
use crate::server::FilesystemServer;
use clap::Parser;
mod sandbox;
use once_cell::sync::OnceCell;
use sandbox::Sandbox;
use std::sync::Arc;

static SANDBOX: OnceCell<Arc<Sandbox>> = OnceCell::new();

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
    // Initialize the tracing subscriber with file and stdout logging
    let args = Args::parse();
    init_tracing();
    tracing::info!("---- Starting Filesystem MCP Server ----");
    tracing::info!("Using root folders: {:?}", &args.roots);
    let sandbox = Arc::new(
        Sandbox::new(args.roots)
            .await
            .with_context(|| "Could not add root")?,
    );

    SANDBOX
        .set(sandbox)
        .map_err(|_| anyhow::anyhow!("Sandbox already initialized"))?;

    // Streamable http server

    let service = transport::streamable_http_server::StreamableHttpService::new(
        || Ok(FilesystemServer::new()),
        transport::streamable_http_server::session::local::LocalSessionManager::default().into(),
        Default::default(),
    );
    // Create the router and nest the MCP service
    let router = axum::Router::new().nest_service("/mcp", service.clone());
    // Bind to localhost on port 3000 (or your preferred port)
    let listener = tokio::net::TcpListener::bind("127.0.0.1:8084")
        .await
        .map_err(|e| anyhow::anyhow!("Failed to bind to port: {}", e))?;

    tracing::info!("Server listening on http://127.0.0.1:8084/mcp");
    // Start the HTTP server
    axum::serve(listener, router)
        .await
        .map_err(|e| anyhow::anyhow!("Server error: {}", e))?;
    Ok(())
}
