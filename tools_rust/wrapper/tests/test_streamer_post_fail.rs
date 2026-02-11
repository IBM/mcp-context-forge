use bytes::Bytes;
use contextforge_stdio_wrapper::config::Config;
use contextforge_stdio_wrapper::http_client::get_http_client;
use contextforge_stdio_wrapper::streamer::McpStreamClient;
use mockito::Server;

#[tokio::test]
pub async fn test_streamer_post() -> Result<(), Box<dyn std::error::Error>> {
    let mut server = Server::new_async().await;
    let url = format!("{}/mcp/", server.url());

    let mock_init = server
        .mock("POST", "/mcp/")
        .with_status(500)
        .with_body("error")
        .create_async()
        .await;
    let config = Config::from_cli(["test", "--url", url.as_str()]);
    let http_client = get_http_client(&config).await.map_err(|e| e.clone())?;
    let cli = McpStreamClient::try_new(config)?;

    let out = cli.stream_post(&http_client, Bytes::from("ini")).await;
    assert!(out.is_err());
    mock_init.assert_async().await;
    Ok(())
}
