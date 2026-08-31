use bytes::Bytes;
use mcp_stdio_wrapper::config::{Config, DEFAULT_AUTH};
use mcp_stdio_wrapper::http_client::get_http_client;
use mcp_stdio_wrapper::streamer::McpStreamClient;
use mockito::Server;

const INIT: &str = r#"{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"prompts":{},"resources":{},"tools":{}},"serverInfo":{"name":"rmcp","version":"0.13.0"},"instructions":"This server provides counter tools and prompts. Tools: increment, decrement, get_value, say_hello, echo, sum. Prompts: example_prompt (takes a message), counter_analysis (analyzes counter state with a goal)."}}"#;
const INIT_OUT: &str = r#"data:
id: 0
retry: 3000

data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"prompts":{},"resources":{},"tools":{}},"serverInfo":{"name":"rmcp","version":"0.13.0"},"instructions":"This server provides counter tools and prompts. Tools: increment, decrement, get_value, say_hello, echo, sum. Prompts: example_prompt (takes a message), counter_analysis (analyzes counter state with a goal)."}}
"#;
const NOTIFY: &str = r#"{"jsonrpc":"2.0","method": "notifications/initialized"}"#;

/// Tests the streamer post failure case.
///
/// # Errors
///
/// Returns an error if the mock server setup fails.
///
/// # Panics
///
/// Panics if the mock server does not receive the expected request.
#[tokio::test]
pub async fn test_streamer_post() -> Result<(), Box<dyn std::error::Error>> {
    let mut server = Server::new_async().await;
    let url = server.url();

    let mock_init = server
        .mock("POST", "/mcp/")
        .match_header("authorization", "token")
        .match_header("content-type", "application/json")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_header("mcp-session-id", "9cb62a01-2523-4380-964e-2e3efd1d135a")
        .with_body(INIT_OUT)
        .create_async()
        .await;

    let mock_notify = server
        .mock("POST", "/mcp/")
        .match_header("authorization", "token")
        .match_header("mcp-session-id", "9cb62a01-2523-4380-964e-2e3efd1d135a")
        .with_status(202)
        .with_body("")
        .create_async()
        .await;

    let mut authorization_header = DEFAULT_AUTH;
    if authorization_header.is_none() {
        authorization_header = Some("token");
    }

    let config = Config::from_cli([
        "test",
        "--url",
        &format!("{url}/mcp/"),
        "--auth",
        authorization_header.unwrap(),
    ]);
    assert!(!format!("{config:?}").contains("token"));

    let http_client = get_http_client(&config).await.map_err(|e| e.clone())?;
    let cli = McpStreamClient::try_new(config)?;
    assert!(!format!("{cli:?}").contains("token"));

    let out = cli.stream_post(&http_client, Bytes::from(INIT)).await?;
    mock_init.assert_async().await;
    assert!(out.sse);
    assert_eq!(
        out.out,
        vec![
            Bytes::from_static(b"data:"),
            Bytes::from_static(b"id: 0"),
            Bytes::from_static(b"retry: 3000"),
            Bytes::from_static(b"data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{\"prompts\":{},\"resources\":{},\"tools\":{}},\"serverInfo\":{\"name\":\"rmcp\",\"version\":\"0.13.0\"},\"instructions\":\"This server provides counter tools and prompts. Tools: increment, decrement, get_value, say_hello, echo, sum. Prompts: example_prompt (takes a message), counter_analysis (analyzes counter state with a goal).\"}}"),
        ]
    );

    let out = cli.stream_post(&http_client, Bytes::from(NOTIFY)).await?;
    mock_notify.assert_async().await;
    assert!(!out.sse);
    assert!(out.out.is_empty());
    Ok(())
}
