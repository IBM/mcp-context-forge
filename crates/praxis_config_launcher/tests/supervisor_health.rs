use std::net::SocketAddr;

use praxis_config_launcher::health::{HealthState, serve, validate_listen_address};
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};

async fn status(address: std::net::SocketAddr, path: &str) -> String {
    let mut stream = tokio::net::TcpStream::connect(address)
        .await
        .expect("connect health server");
    stream
        .write_all(
            format!("GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .await
        .expect("request");
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .await
        .expect("response");
    response.lines().next().expect("status line").to_owned()
}

async fn raw_response(address: SocketAddr, request: &[u8]) -> String {
    let mut stream = tokio::net::TcpStream::connect(address)
        .await
        .expect("connect health server");
    stream.write_all(request).await.expect("request");
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .await
        .expect("bounded response");
    response
}

#[tokio::test]
async fn supervisor_health_is_live_while_readiness_requires_exact_active_generation() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("health listener");
    let address = listener.local_addr().expect("address");
    let state = HealthState::default();
    let server = tokio::spawn(serve(listener, state.clone()));

    assert!(status(address, "/livez").await.contains("200 OK"));
    assert!(
        status(address, "/readyz")
            .await
            .contains("503 Service Unavailable")
    );
    state.ready(&"aa".repeat(32)).await;
    assert!(status(address, "/readyz").await.contains("200 OK"));
    state.unready().await;
    assert!(
        status(address, "/readyz")
            .await
            .contains("503 Service Unavailable")
    );

    server.abort();
}

#[test]
fn supervisor_health_rejects_every_non_loopback_listener() {
    for address in [
        "0.0.0.0:4444",
        "192.0.2.1:4444",
        "[::]:4444",
        "[2001:db8::1]:4444",
    ] {
        let parsed: SocketAddr = address.parse().expect("address");
        assert!(
            validate_listen_address(parsed).is_err(),
            "accepted {address}"
        );
    }
    for address in ["127.0.0.1:0", "[::1]:0"] {
        let parsed: SocketAddr = address.parse().expect("address");
        assert_eq!(validate_listen_address(parsed).expect("loopback"), parsed);
    }
}

#[tokio::test]
async fn supervisor_health_bounds_and_closes_unsupported_requests() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("health listener");
    let address = listener.local_addr().expect("address");
    let server = tokio::spawn(serve(listener, HealthState::default()));

    let unsupported =
        raw_response(address, b"POST /livez HTTP/1.1\r\nHost: localhost\r\n\r\n").await;
    assert!(unsupported.starts_with("HTTP/1.1 404 Not Found\r\n"));
    assert!(unsupported.ends_with("Connection: close\r\n\r\n"));
    let oversized = raw_response(address, &[b'X'; 1_024]).await;
    assert!(oversized.starts_with("HTTP/1.1 413 Payload Too Large\r\n"));

    server.abort();
}

#[tokio::test]
async fn supervisor_health_times_out_incomplete_request() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("health listener");
    let address = listener.local_addr().expect("address");
    let server = tokio::spawn(serve(listener, HealthState::default()));

    let response = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        raw_response(address, b"GET /livez"),
    )
    .await
    .expect("server request timeout");
    assert!(response.starts_with("HTTP/1.1 408 Request Timeout\r\n"));

    server.abort();
}
