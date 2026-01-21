use flume::Sender;
use tokio::io::{self, AsyncBufReadExt, BufReader};
use tracing::debug;

/// stdio reader
pub(crate) fn spawn_reader(tx: Sender<String>) {
    tokio::spawn(async move {
        let stdin = io::stdin();
        let mut reader = BufReader::new(stdin).lines();

        while let Ok(Some(line)) = reader.next_line().await {
            debug!("Read: {line}");
            if tx.send_async(line).await.is_err() {
                break;
            }
        }
    });
}
