use crate::http_client::get_http_client;
use crate::mcp_workers_write::write_output;
use crate::streamer::McpStreamClient;
use crate::streamer_error::mcp_error;
use bytes::Bytes;
use flume::{Receiver, Sender};
use std::sync::Arc;
use tracing::error;

/// creates configured number of workers
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
        get_http_client(&mcp_client.config).await.ok()
    };

    // Spawn workers
    for i in 0..concurrency {
        let rx = input_rx.clone();
        let tx = output_tx.clone();
        let mcp = Arc::clone(mcp_client);
        let template = shared_client.clone();

        handles.push(tokio::spawn(async move {
            // STEP 3: Each worker gets its client handle here
            let h_client = match template {
                Some(existing) => existing, // Use the shared one
                None => {
                    // Create a fresh one for this specific worker
                    match get_http_client(&mcp.config).await {
                        Ok(c) => c,
                        Err(e) => {
                            error!("Worker {i} failed to start: {e}");
                            return; // Stop this worker only
                        }
                    }
                }
            };

            // The Work Loop
            while let Ok(line) = rx.recv_async().await {
                match mcp.stream_post(&h_client, line.clone()).await {
                    Ok(res) => {
                        write_output(i, &tx, res).await;
                    }
                    Err(e) => {
                        error!("Worker {i}: Post failed: {e}");
                        mcp_error(&i, &line, &e, &tx).await;
                    }
                }
            }
        }));
    }

    drop(output_tx);
    handles
}
