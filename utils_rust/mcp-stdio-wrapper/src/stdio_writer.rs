use flume::Receiver;
use tokio::io::{self, AsyncWriteExt, BufWriter};
use tracing::{debug, error, info};

pub fn spawn_writer(rx: Receiver<String>) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut stdout = BufWriter::new(io::stdout());
        while let Ok(message) = rx.recv_async().await {
            debug!("Write: {}", message);
            if let Err(e) = stdout.write_all(message.as_bytes()).await {
                error!("Failed to write to stdout: {}", e);
                break;
            }
            if !message.ends_with('\n') //TODO dz check this
                && let Err(e) = stdout.write_all(b"\n").await
            {
                error!("Failed to write newline to stdout: {}", e);
                break;
            }
            if let Err(e) = stdout.flush().await {
                error!("Failed to flush stdout: {}", e);
                break;
            }
        }
        info!("Writer task shutting down");
    })
}
