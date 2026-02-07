use base64::{engine::general_purpose, Engine as _};
use mcp_stdio_wrapper::config::Config;
use mcp_stdio_wrapper::http_client::get_http_client;
use mcp_stdio_wrapper::streamer_error::invalid_error;
use nom::AsBytes;
use std::fs::File;
use std::io::Write;
use std::path::Path;

/// Tests the HTTP client creation failure when cert file cannot be read.
/// # Errors
/// Returns an error if the mock server setup fails.
/// # Panics
/// Panics if the mock server does not receive the expected request.
#[tokio::test]
#[should_panic(expected = "Failed to read cert file")]
pub async fn test_streamer_cert() {
    let config = Config::from_cli([
        "test",
        "--url",
        "https://localhost:3000/mcp",
        "--tls-cert",
        "?",
    ]);

    let _client = get_http_client(&config).await.unwrap();
}
// Note: reqwest::Certificate::from_pem() is very lenient and accepts many formats
// This test covers the error path that occurs when PEM parsing succeeds but
// the certificate is invalid when added to the client builder
/// # Panics
/// Panics if the HTTP client cannot be built with invalid certificate.

#[tokio::test]
#[should_panic(expected = "Http client build error")]
pub async fn test_streamer_cert_invalid_certificate() {
    const BLOB: &[&str] = &[
        "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUNsamNDQlg0Q0NRQ0t6OFpy",
        "ISEhSU5WQUxJRCEhIUJBU0U2NCEhIURBVEEhISFIRQpMLS0tLS1FTkQgQ0VSVElG",
        "SUNBVEUtLS0tLQo=",
    ];

    let temp_dir = tempfile::tempdir().unwrap();
    let log_file = temp_dir.path().join("invalid-cert.pem");
    let log_path = log_file.to_str().unwrap();
    let mut file = File::create(&log_file).unwrap();
    let broken = general_purpose::STANDARD
        .decode(BLOB.join(""))
        .expect("Failed to decode test data");

    let _ = file.write_all(broken.as_bytes());

    let config = Config::from_cli([
        "test",
        "--url",
        "https://localhost:3000/mcp",
        "--tls-cert",
        log_path,
    ]);

    let e = reqwest::Client::new().get("").build().unwrap_err();
    let _msg = invalid_error(Path::new("/tmp"), &e);

    let _client = get_http_client(&config).await.unwrap();
}
