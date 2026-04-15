use crate::stdio_process::process_message;
use bytes::Bytes;
use flume::Receiver;
use tokio::io::{AsyncWrite, BufWriter};
use tracing::{error, info};

// We make the function generic over W (any AsyncWriter)
pub fn spawn_writer<W>(rx: Receiver<Bytes>, writer: W) -> tokio::task::JoinHandle<()>
where
    W: AsyncWrite + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut stdout = BufWriter::new(writer);
        while let Ok(message) = rx.recv_async().await {
            if let Err(e) = process_message(&rx, &mut stdout, &message).await {
                error!("Failed to process message in writer: {}", e);
                break;
            }
        }
        info!("Writer task shutting down");
    })
}
