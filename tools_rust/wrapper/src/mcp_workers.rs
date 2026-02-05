use crate::http_client::get_http_client;
use crate::mcp_workers_write::write_output;
use crate::streamer::McpStreamClient;
use crate::streamer_error::mcp_error;
use bytes::Bytes;
use flume::{Receiver, Sender};
use nom::AsBytes;
use std::sync::Arc;
use tracing::{debug, error};
/// creates configured number of workers
pub async fn spawn_workers(
    concurrency: usize,
    mcp_client: &Arc<McpStreamClient>,
    input_rx: &Receiver<Bytes>,
    output_tx: Sender<Bytes>,
) -> Vec<tokio::task::JoinHandle<()>> {
    let mut handles = Vec::with_capacity(concurrency);
    
    // Create shared HTTP client if not using per-worker pools
    let shared_client = if mcp_client.config.http_pool_per_worker {
        None
    } else {
        match get_http_client(&mcp_client.config).await {
            Ok(client) => Some(client),
            Err(e) => {
                error!(
                    "Failed to create shared HTTP client, \
                    falling back to per-worker clients: {}",
                    e
                );
                None
            }
        }
    };

    for i in 0..concurrency {
        let rx = input_rx.clone();
        let tx = output_tx.clone();
        let client = mcp_client.clone();

        // Use shared client or create per-worker client
        let h_client = if let Some(ref shared) = shared_client {
            shared.clone()
        } else {
            match get_http_client(&mcp_client.config).await {
                Ok(c) => c,
                Err(e) => {
                    error!("Worker {i}: Failed to create HTTP client: {e}. Aborting.");
                    panic!("Failed to create HTTP client for worker {i}: {e}");
                }
            }
        };

        let handle = tokio::spawn(async move {
            while let Ok(line) = rx.recv_async().await {
                debug!(
                    "Worker {i} processing message: {}",
                    String::from_utf8_lossy(&line)
                );
                let response = client.stream_post(&h_client, line.clone()).await;
                match response {
                    Ok(res) => {
                        write_output(i, &tx, res).await;
                    }
                    Err(e) => {
                        error!("Worker {i}: Post failed: {e}");

                        mcp_error(&i, line.as_bytes(), &e, &tx).await;
                    }
                }
            }
            debug!("Worker {} shutting down", i);
        });
        handles.push(handle);
    }
    drop(output_tx);
    handles
}
