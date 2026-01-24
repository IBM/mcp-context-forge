use crate::sandbox::Sandbox;
use crate::server::{AppContext, FilesystemServer};
use anyhow::{Context, Result};
use rmcp::transport;
use std::sync::Arc;
use tracing_subscriber::EnvFilter;

pub mod sandbox;
pub mod server;
pub mod tools;

pub static DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:8084";
pub static APP_NAME: &str = env!("CARGO_PKG_NAME");
pub static APP_VERSION: &str = env!("CARGO_PKG_VERSION");
pub static MAX_FILE_SIZE: u64 = 1024 * 1024;

pub fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new("INFO"))
        .with_ansi(true)
        .try_init();
}

pub async fn build_router(roots: Vec<String>) -> Result<axum::Router> {
    let sandbox = Arc::new(Sandbox::new(roots).await.context("Could not add roots")?);
    let processed_roots = &sandbox.get_roots();
    let ctx = Arc::new(AppContext { sandbox });

    let service = transport::streamable_http_server::StreamableHttpService::new(
        {
            let ctx = ctx.clone();
            move || Ok(FilesystemServer::new(ctx.clone()))
        },
        transport::streamable_http_server::session::local::LocalSessionManager::default().into(),
        Default::default(),
    );
    print_startup_banner(processed_roots);
    Ok(axum::Router::new().nest_service("/mcp", service))
}

pub fn print_startup_banner(roots: &Vec<String>) {
    tracing::info!(
"
----------- MCP SERVER -----------
  App        :  {}
  Version    :  {}
  Roots      :  {:?}
  Transport  :  Streamable-HTTP
  Listening  :  http://{}/mcp
",
        APP_NAME,
        APP_VERSION,
        roots,
        DEFAULT_BIND_ADDRESS,
    );
}
