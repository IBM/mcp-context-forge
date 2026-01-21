use crate::streamer::McpStreamClient;
use reqwest::header::{ACCEPT, CONTENT_TYPE};
use reqwest::{header, Client};
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::error;

impl McpStreamClient {
    #[allow(unused)]
    /// Initialize the client with standard MCP/SSE headers
    pub fn new(url: String) -> Self {
        let mut headers = header::HeaderMap::new();
        headers.insert(
            ACCEPT,
            header::HeaderValue::from_static("application/json, text/event-stream"),
        );
        headers.insert(
            CONTENT_TYPE,
            header::HeaderValue::from_static("application/json"),
        );

        let client = Client::builder()
            .default_headers(headers)
            .tcp_keepalive(Duration::from_secs(60))
            .build()
            .unwrap_or_else(|error| {
                // Log to standard error (standard for CLI tools)
                error!("Error: {error}");
                // Terminate with code 1 (or 255 for -1 equivalent)
                std::process::exit(1);
            });

        Self {
            client,
            url,
            session_id: RwLock::new(None),
        }
    }
}
