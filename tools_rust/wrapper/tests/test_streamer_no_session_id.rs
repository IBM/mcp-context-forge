use http::Response as HttpResponse;
use mcp_stdio_wrapper::config::Config;
use mcp_stdio_wrapper::streamer::McpStreamClient;

/// # Panics
/// * test fails
/// # Errors
/// * test setup fails
#[tokio::test]
pub async fn test_streamer_no_session_id() -> Result<(), Box<dyn std::error::Error>> {
    let response_builder = HttpResponse::builder().status(200);

    let http_res = response_builder.body("")?;

    let response: reqwest::Response = http_res.into();

    let config = Config::from_cli(["test", "--url", "file:///tmp"]);

    let client = McpStreamClient::try_new(config)?;
    assert!(!client.is_auth());
    let result: Option<String> = client.process_session_id(&response);
    assert!(
        result.is_none(),
        "Should return None when session id not found"
    );

    Ok(())
}
