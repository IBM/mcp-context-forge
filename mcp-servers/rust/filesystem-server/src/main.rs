use anyhow::{Context, Result};
use clap::Parser;
use filesystem_server::{DEFAULT_BIND_ADDRESS, build_router, init_tracing};
use tokio::net::TcpListener;

#[derive(Parser, Debug)]
struct Args {
    #[arg(long = "roots", value_delimiter = ' ')]
    roots: Vec<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    init_tracing();

    let router = build_router(args.roots).await?;

    let listener = TcpListener::bind(DEFAULT_BIND_ADDRESS)
        .await
        .context("Failed to bind to port")?;

    axum::serve(listener, router)
        .with_graceful_shutdown(async {
            tokio::signal::ctrl_c().await.unwrap();
        })
        .await?;

    Ok(())
}
