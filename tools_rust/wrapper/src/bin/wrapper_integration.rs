use rmcp::{
    ClientHandler, ServiceExt,
    model::CallToolRequestParams,
    transport::{ConfigureCommandExt, TokioChildProcess},
};
use std::env;
use tokio::process::Command;

#[derive(Clone, Debug, Default)]
pub struct IntegrationClient;

impl ClientHandler for IntegrationClient {}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    check_fast_time_server().await?;

    let client = IntegrationClient
        .serve(TokioChildProcess::new(
            Command::new(env::var("WRAPPER_BIN").expect("WRAPPER_BIN env var required")).configure(
                |cmd| {
                    cmd.args([
                        "--url",
                        &env::var("URL").expect("URL env var required"),
                        "--auth",
                        &env::var("AUTH").expect("AUTH env var required"),
                        "--log-level",
                        "debug",
                    ]);
                },
            ),
        )?)
        .await?;

    let tools = client.list_all_tools().await?;
    println!("Discovered {} tools", tools.len());
    assert!(
        tools.iter().any(|t| t.name == "fast-time-get-system-time"),
        "Tool 'fast-time-get-system-time' not found in: {:?}",
        tools.iter().map(|t| &t.name).collect::<Vec<_>>()
    );

    let args = rmcp::object!({ "timezone": "UTC" });

    // Retry up to 10 times to allow the wrapper to establish its upstream connection
    for attempt in 1..=10 {
        let out = client
            .call_tool(
                CallToolRequestParams::new("fast-time-get-system-time")
                    .with_arguments(args.clone()),
            )
            .await?;

        if !out.is_error.unwrap_or(false) {
            println!("Tool call succeeded on attempt {attempt}");
            client.cancel().await?;
            return Ok(());
        }
        eprintln!("Tool call returned error on attempt {attempt}, retrying...");
    }

    client.cancel().await?;
    panic!("Tool call failed after 10 attempts");
}

async fn check_fast_time_server() -> Result<(), reqwest::Error> {
    let body = reqwest::Client::new()
        .get("http://localhost:8080/health")
        .send()
        .await?
        .text()
        .await?;

    println!("fast-time-server health: {body}");
    Ok(())
}
