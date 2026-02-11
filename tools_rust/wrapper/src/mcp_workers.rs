use crate::http_client::get_http_client;
use crate::mcp_workers_write::write_output;
use crate::streamer::McpStreamClient;
use crate::streamer_error::mcp_error;
use bytes::Bytes;
use flume::{Receiver, Sender};
use std::sync::Arc;
use tracing::{error, warn};

const MAX_RETRIES: u32 = 5;
const BASE_DELAY_MS: u64 = 250;
const MAX_DELAY_MS: u64 = 8000;

/// Creates configured number of workers
/// # Panics
/// when http client build fails
pub async fn spawn_workers(
    concurrency: usize,
    mcp_client: &Arc<McpStreamClient>,
    input_rx: &Receiver<Bytes>,
    output_tx: Sender<Bytes>,
) -> Vec<tokio::task::JoinHandle<()>> {
    let mut handles = Vec::with_capacity(concurrency);

    // Create a shared client if not using per-worker pools
    let shared_client = if mcp_client.config.http_pool_per_worker {
        None
    } else {
        match get_http_client(&mcp_client.config).await {
            Ok(c) => Some(c),
            Err(e) => {
                warn!("Shared HTTP client creation failed, falling back to per-worker pools: {e}");
                None
            }
        }
    };

    // Spawn workers
    for i in 0..concurrency {
        let rx = input_rx.clone();
        let tx = output_tx.clone();
        let mcp = Arc::clone(mcp_client);
        let template = shared_client.clone();

        handles.push(tokio::spawn(async move {
            let h_client = match template {
                Some(existing) => existing,
                None => {
                    match get_http_client(&mcp.config).await {
                        Ok(c) => c,
                        Err(e) => {
                            error!("Worker {i} failed to start: {e}");
                            return;
                        }
                    }
                }
            };

            while let Ok(line) = rx.recv_async().await {
                let mut last_err = String::new();
                let mut succeeded = false;

                for attempt in 0..=MAX_RETRIES {
                    match mcp.stream_post(&h_client, line.clone()).await {
                        Ok(res) => {
                            write_output(i, &tx, res).await;
                            succeeded = true;
                            break;
                        }
                        Err(e) => {
                            last_err = e;
                            if attempt < MAX_RETRIES {
                                let delay = (BASE_DELAY_MS * 2u64.pow(attempt)).min(MAX_DELAY_MS);
                                warn!(
                                    "Worker {i}: attempt {}/{MAX_RETRIES} failed: {last_err}, retrying in {delay}ms",
                                    attempt + 1
                                );
                                tokio::time::sleep(tokio::time::Duration::from_millis(delay)).await;
                            }
                        }
                    }
                }

                if !succeeded {
                    error!("Worker {i}: all {MAX_RETRIES} retries exhausted: {last_err}");
                    mcp_error(&i, &line, &last_err, &tx).await;
                }
            }
        }));
    }

    drop(output_tx);
    handles
}
