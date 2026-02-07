use bytes::Bytes;
use mcp_stdio_wrapper::logger::init_logger;
use mcp_stdio_wrapper::stdio_writer::spawn_writer;
use tokio_test::io::Builder;
///
/// # Errors
/// * test fails
/// # Panics
/// * test fails
#[tokio::test]
pub async fn test_writer() -> Result<(), Box<dyn std::error::Error>> {
    init_logger(Some("debug"), None);
    let (tx, rx) = flume::unbounded::<Bytes>();

    let out = Builder::new().write(b"test\n").build();

    let writer = spawn_writer(rx, out);
    tx.send_async(Bytes::from("test")).await?;
    drop(tx);
    writer.await?;
    Ok(())
}

/// Test writer error handling when write fails
/// # Errors
/// * test fails
/// # Panics
/// * test fails
#[tokio::test]
pub async fn test_writer_error() -> Result<(), Box<dyn std::error::Error>> {
    init_logger(Some("debug"), None);
    let (tx, rx) = flume::unbounded::<Bytes>();

    // Create a mock writer that will fail on write
    let out = Builder::new()
        .write_error(std::io::Error::new(
            std::io::ErrorKind::BrokenPipe,
            "simulated write error",
        ))
        .build();

    let writer = spawn_writer(rx, out);

    // Send a message that will trigger the write error
    tx.send_async(Bytes::from("test message")).await?;

    // Give the writer task time to process and fail
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

    // Drop the sender to allow the writer to shut down
    drop(tx);

    // Wait for the writer task to complete
    writer.await?;

    Ok(())
}
