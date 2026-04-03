use contextforge_validation_sidecar::{
    protocol::{ValidationRequest, ValidationResponseEnvelope, read_frame, write_json_frame},
    serve_until,
    validator::{DEFAULT_DANGEROUS_PATTERNS, ParserBackend},
};
use tempfile::tempdir;
use tokio::{
    net::{UnixListener, UnixStream},
    sync::oneshot,
};

#[tokio::test]
async fn runtime_serves_one_happy_path_request_over_uds() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let listener = UnixListener::bind(&socket_path).expect("bind listener");
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

    let server = tokio::spawn(async move {
        serve_until(listener, ParserBackend::SimdJson, async move {
            let _ = shutdown_rx.await;
        })
        .await
        .expect("sidecar server");
    });

    let mut stream = UnixStream::connect(&socket_path).await.expect("connect");
    let dangerous_patterns = DEFAULT_DANGEROUS_PATTERNS
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let request = ValidationRequest::from_raw_body(br#"{"name":"safe"}"#, 64, &dangerous_patterns)
        .expect("request")
        .to_envelope();

    write_json_frame(&mut stream, &request)
        .await
        .expect("write request");
    let payload = read_frame(&mut stream).await.expect("read response");
    let response: ValidationResponseEnvelope =
        serde_json::from_slice(&payload).expect("decode response");

    assert_eq!(response, ValidationResponseEnvelope::ok());

    let _ = shutdown_tx.send(());
    server.await.expect("server join");
}
