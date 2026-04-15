use bytes::Bytes;
use mcp_stdio_wrapper::config::{Config, DEFAULT_CONCURRENCY};

use mcp_stdio_wrapper::logger::init_logger;
use mcp_stdio_wrapper::mcp_workers::*;
use mcp_stdio_wrapper::streamer::McpStreamClient;
use mockito::Server;
use std::sync::Arc;

/// Tests that `spawn_workers` correctly processes a message by sending it to a mock server
/// and forwarding the response.
/// # Errors
/// Returns an error if channel operations fail or if the test times out.
/// # Panics
/// Panics if an assertion fails.
#[tokio::test]
pub async fn test_mcp_workers() -> Result<(), Box<dyn std::error::Error>> {
    init_logger(Some("debug"), None);
    let mut server = Server::new_async().await;

    let expected = "ok";

    let url = server.url();
    for opt in [None, Some("--http-pool-per-worker")] {
        let mock_init = server
            .mock("POST", "/mcp/")
            .with_status(200)
            .with_header("mcp-session-id", "session-42")
            .with_header("content-type", "text/event-stream") // sse emulation
            .with_body(format!("data: {expected}"))
            .create_async()
            .await;

        let url = format!("{url}/mcp/");
        let args: Vec<&str> = [Some("test"), Some("--url"), Some(url.as_str()), opt]
            .into_iter()
            .flatten() // Discards the None
            .collect();
        let config = Config::from_cli(args);

        let client = McpStreamClient::try_new(config)?;
        let (tx_in, rx_in) = flume::unbounded();
        let (tx_out, rx_out) = flume::unbounded();

        let _ = spawn_workers(DEFAULT_CONCURRENCY, &Arc::new(client), &rx_in, tx_out).await;
        tx_in.send_async(Bytes::from("init")).await?;

        let out = rx_out.recv_async().await?;

        assert_eq!(expected, String::from_utf8_lossy(&out));
        mock_init.assert_async().await;
    }
    Ok(())
}
