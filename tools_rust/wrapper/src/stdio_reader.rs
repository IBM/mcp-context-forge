use bytes::Bytes;
use flume::Sender;
use tokio::io::{AsyncBufReadExt, AsyncRead, BufReader};
use tokio::task::JoinHandle;
use tracing::debug;

/// stdio reader
pub fn spawn_reader<R>(tx: Sender<Bytes>, reader: R) -> JoinHandle<()>
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut reader = BufReader::new(reader).lines();

        while let Ok(Some(line)) = reader.next_line().await {
            debug!("Read: {line}");
            if tx.send_async(Bytes::from(line)).await.is_err() {
                debug!("Reader loop terminated");
                break;
            }
        }
        debug!("Exit reader loop");
    })
}
