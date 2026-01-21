use mcp_stdio_wrapper::logger::init_logger;
use mcp_stdio_wrapper::streamer::McpStreamClient;
use tracing::{debug, error, info};

const URL: &str = "http://localhost:8000/mcp";
pub const INIT: &str = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"wrapper","version":"0.0.1"}}}"#;

#[tokio::main]
async fn main() {
    init_logger();

    let client = McpStreamClient::new(URL.to_owned());

    debug!("Start {client:?}");

    let result = client.stream_post(INIT.to_string()).await;
    match result {
        Ok(post_data) => {
            debug!("Post {post_data:?}");
        }
        Err(e) => {
            error!("Error: {e}");
        }
    }
}
