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

static DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:8084";
static APP_NAME: &str = env!("CARGO_PKG_NAME");
static APP_VERSION: &str = env!("CARGO_PKG_VERSION");
static MAX_FILE_SIZE: u64 = 1024 * 1024;

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
    tracing::info!("---- Starting FILESYSTEM MCP Server ----");

    // Initialize sandbox once
    let sandbox = Arc::new(
        Sandbox::new(args.roots.clone())
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
    let listener = tokio::net::TcpListener::bind(DEFAULT_BIND_ADDRESS)
        .await
        .context("Failed to bind to port")?;

    tracing::info!(
        app = APP_NAME,
        version = APP_VERSION,
        addr = DEFAULT_BIND_ADDRESS,
        "Server starting"
    );

    tracing::info!(
        roots = ?&args.roots,
        transport = "streamable-http",
        "Configuration loaded"
    );

    tracing::info!(
        url = format!("http://{}/mcp", DEFAULT_BIND_ADDRESS),
        "Server ready"
    );

    // Serve
    axum::serve(listener, router)
        .with_graceful_shutdown(async {
            tokio::signal::ctrl_c().await.unwrap();
            tracing::info!("Shutting down...");
        })
        .await
        .context("Server error")?;

    tracing::info!("Server stopped");
    Ok(())
}
