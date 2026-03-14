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
    for (key, value) in env::vars() {
        println!("ENV: {key} = {value}");
    }
    let client = IntegrationClient
        .serve(TokioChildProcess::new(
            Command::new(env::var("WRAPPER_BIN")?).configure(|cmd| {
                cmd.args([
                    "--url",
                    &env::var("URL").unwrap(),
                    "--auth",
                    &env::var("AUTH").unwrap(),
                    "--log-level",
                    "debug",
                ]);
            }),
        )?)
        .await?;

    let tools = client.list_all_tools().await?;
    println!("{tools:?}");
    assert!(
        tools.iter().any(|t| t.name == "fast-time-get-system-time"),
        "Tool not found"
    );

    let args = rmcp::object!({ "timezone": "UTC" });

    for _ in 0..42 {
        let out = client
            .call_tool(
                CallToolRequestParams::new("fast-time-get-system-time")
                    .with_arguments(args.clone()),
            )
            .await?;

        println!("{out:?}");
        if !out.is_error.unwrap() {
            client.cancel().await?;
            return Ok(());
        }
    }
    panic!("Fail");
}

async fn check_fast_time_server() -> Result<(), reqwest::Error> {
    let body = reqwest::Client::new()
        .get("http://localhost:8080/health")
        .send()
        .await?
        .text()
        .await?;

    println!("{body}");
    Ok(())
}
