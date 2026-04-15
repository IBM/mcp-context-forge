use crate::config::Config;
use crate::mcp_workers::spawn_workers;
use crate::stdio_reader::spawn_reader;
use crate::stdio_writer::spawn_writer;
use crate::streamer::McpStreamClient;
use bytes::Bytes;
use std::sync::Arc;
use tokio::io::{AsyncRead, AsyncWrite, BufReader, BufWriter};
use tracing::{debug, error};

const CHANNEL_CAPACITY_PER_WORKER: usize = 16;

pub(crate) fn channel_capacity(concurrency: usize) -> usize {
    concurrency.max(1) * CHANNEL_CAPACITY_PER_WORKER
}

pub async fn main_loop<R, W>(config: Config, reader: R, writer: W)
where
    R: AsyncRead + Unpin + Send + 'static,
    W: AsyncWrite + Unpin + Send + 'static,
{
    let reader = BufReader::with_capacity(256 * 1024, reader);
    let writer = BufWriter::with_capacity(512 * 1024, writer);
    let concurrency = config.concurrency;
    let client = match McpStreamClient::try_new(config) {
        Ok(client) => client,
        Err(e) => {
            error!("Error {e}");
            return;
        }
    };
    let mcp_client = Arc::new(client);
    debug!(
        session_id_present = mcp_client.is_ready(),
        "Mcp client initialized"
    );

    // (Reader -> Worker)
    let queue_capacity = channel_capacity(concurrency);
    let (reader_tx, reader_rx) = flume::bounded::<Bytes>(queue_capacity);
    // (Worker -> Writer)
    let (writer_tx, writer_rx) = flume::bounded::<Bytes>(queue_capacity);

    spawn_reader(reader_tx, reader);

    // create several workers (limit with concurrenty parameter)

    let worker_handles = spawn_workers(concurrency, &mcp_client, &reader_rx, writer_tx).await;

    let exit = spawn_writer(writer_rx, writer);

    // Wait for writer to finish
    let _ = exit.await;

    // Wait for all workers to complete and detect panics
    for (i, handle) in worker_handles.into_iter().enumerate() {
        if let Err(e) = handle.await {
            error!("Worker {} panicked: {:?}", i, e);
        }
    }

    debug!("Finish");
}

#[cfg(test)]
mod tests {
    use super::channel_capacity;

    #[test]
    fn channel_capacity_scales_with_concurrency() {
        assert_eq!(channel_capacity(0), 16);
        assert_eq!(channel_capacity(1), 16);
        assert_eq!(channel_capacity(4), 64);
    }
}
