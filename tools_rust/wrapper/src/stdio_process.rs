use bytes::Bytes;
use flume::Receiver;
use tokio::io::{self, AsyncWrite, AsyncWriteExt, BufWriter};
use tracing::debug;

/// process a single message
/// # Errors
/// * error happens on stream close
pub async fn process_message<W>(
    rx: &Receiver<Bytes>,
    stdout: &mut BufWriter<W>,
    message: &Bytes,
) -> io::Result<()>
where
    W: AsyncWrite + Unpin + Send + 'static,
{
    debug!("Write: {}", String::from_utf8_lossy(message));
    write_and_append_newline(stdout, message).await?;
    // if messages ready to send
    while let Ok(next_msg) = rx.try_recv() {
        write_and_append_newline(stdout, &next_msg).await?;
    }
    stdout.flush().await?;
    Ok(())
}

async fn write_and_append_newline<W: AsyncWrite + Unpin>(
    stdout: &mut BufWriter<W>,
    msg: &Bytes,
) -> tokio::io::Result<()> {
    stdout.write_all(msg).await?;
    if !msg.ends_with(b"\n") {
        stdout.write_all(b"\n").await?;
    }
    Ok(())
}
