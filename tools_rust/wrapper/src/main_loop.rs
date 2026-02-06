use crate::config::Config;
use crate::mcp_workers::spawn_workers;
use crate::stdio_reader::spawn_reader;
use crate::stdio_writer::spawn_writer;
use crate::streamer::McpStreamClient;
use bytes::Bytes;
use std::sync::Arc;
use tokio::io::{AsyncRead, AsyncWrite, BufReader, BufWriter};
use tracing::{debug, error};

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
    debug!("Mcp client: {mcp_client:?}");

    // (Reader -> Worker)
    let (reader_tx, reader_rx) = flume::unbounded::<Bytes>();
    // (Worker -> Writer)
    let (writer_tx, writer_rx) = flume::unbounded::<Bytes>();

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
