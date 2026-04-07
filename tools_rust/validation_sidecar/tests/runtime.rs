use contextforge_validation_sidecar::{
    ServerConfig, prepare_listener,
    protocol::{
        ValidationRequest, ValidationResponseEnvelope, encode_request_payload, read_frame,
        write_frame,
    },
    serve_until,
    validator::DEFAULT_DANGEROUS_PATTERNS,
};
use std::{os::unix::fs::PermissionsExt, time::Duration};
use tempfile::tempdir;
use tokio::{
    net::{UnixListener, UnixStream},
    sync::oneshot,
    time::sleep,
};

#[tokio::test]
async fn runtime_serves_one_happy_path_request_over_uds() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let listener = UnixListener::bind(&socket_path).expect("bind listener");
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let server_socket_path = socket_path.clone();

    let server = tokio::spawn(async move {
        serve_until(
            listener,
            ServerConfig::new(server_socket_path),
            async move {
                let _ = shutdown_rx.await;
            },
        )
        .await
        .expect("sidecar server");
    });

    let mut stream = UnixStream::connect(&socket_path).await.expect("connect");
    let dangerous_patterns = DEFAULT_DANGEROUS_PATTERNS
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let request = ValidationRequest::from_raw_body(br#"{"name":"safe"}"#, 64, &dangerous_patterns)
        .expect("request");

    let payload = encode_request_payload(&request).expect("payload");
    write_frame(&mut stream, &payload)
        .await
        .expect("write request");
    let response_payload = read_frame(&mut stream).await.expect("read response");
    let response: ValidationResponseEnvelope =
        serde_json::from_slice(&response_payload).expect("decode response");

    assert_eq!(response, ValidationResponseEnvelope::ok());

    let _ = shutdown_tx.send(());
    server.await.expect("server join");
}

#[tokio::test]
async fn runtime_reuses_one_socket_for_multiple_requests_and_healthchecks() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let listener = UnixListener::bind(&socket_path).expect("bind listener");
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let server_socket_path = socket_path.clone();

    let server = tokio::spawn(async move {
        serve_until(
            listener,
            ServerConfig::new(server_socket_path),
            async move {
                let _ = shutdown_rx.await;
            },
        )
        .await
        .expect("sidecar server");
    });

    let mut stream = UnixStream::connect(&socket_path).await.expect("connect");
    let dangerous_patterns = DEFAULT_DANGEROUS_PATTERNS
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>();

    let healthcheck = ValidationRequest {
        raw_body: br#"{}"#.to_vec(),
        max_param_length: 1,
        dangerous_patterns: Vec::new(),
        request_id: None,
        healthcheck: true,
    };
    let payload = encode_request_payload(&healthcheck).expect("healthcheck payload");
    write_frame(&mut stream, &payload)
        .await
        .expect("write healthcheck");
    let response_payload = read_frame(&mut stream)
        .await
        .expect("read healthcheck response");
    let response: ValidationResponseEnvelope =
        serde_json::from_slice(&response_payload).expect("decode healthcheck response");
    assert_eq!(response, ValidationResponseEnvelope::ok());

    let safe_request =
        ValidationRequest::from_raw_body(br#"{"name":"safe"}"#, 64, &dangerous_patterns)
            .expect("request");
    let payload = encode_request_payload(&safe_request).expect("payload");
    write_frame(&mut stream, &payload)
        .await
        .expect("write safe request");
    let response_payload = read_frame(&mut stream).await.expect("read safe response");
    let response: ValidationResponseEnvelope =
        serde_json::from_slice(&response_payload).expect("decode safe response");
    assert_eq!(response, ValidationResponseEnvelope::ok());

    let _ = shutdown_tx.send(());
    server.await.expect("server join");
}

#[tokio::test]
async fn runtime_returns_rejection_envelope_for_blocked_input() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let listener = UnixListener::bind(&socket_path).expect("bind listener");
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let server_socket_path = socket_path.clone();

    let server = tokio::spawn(async move {
        serve_until(
            listener,
            ServerConfig::new(server_socket_path),
            async move {
                let _ = shutdown_rx.await;
            },
        )
        .await
        .expect("sidecar server");
    });

    let mut stream = UnixStream::connect(&socket_path).await.expect("connect");
    let dangerous_patterns = DEFAULT_DANGEROUS_PATTERNS
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let request = ValidationRequest::from_raw_body(
        br#"{"name":"<script>alert(1)</script>"}"#,
        64,
        &dangerous_patterns,
    )
    .expect("request");

    let payload = encode_request_payload(&request).expect("payload");
    write_frame(&mut stream, &payload)
        .await
        .expect("write request");
    let response_payload = read_frame(&mut stream)
        .await
        .expect("read rejection response");
    let response: ValidationResponseEnvelope =
        serde_json::from_slice(&response_payload).expect("decode rejection response");

    assert_eq!(
        response,
        ValidationResponseEnvelope::rejected(
            "name",
            "dangerous_pattern",
            "Parameter name contains dangerous characters"
        )
    );

    let _ = shutdown_tx.send(());
    server.await.expect("server join");
}

#[tokio::test]
async fn prepare_listener_creates_owner_only_socket_permissions() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let config = ServerConfig {
        uds_path: socket_path.clone(),
        connection_idle_timeout: Duration::from_millis(250),
        max_connections: 16,
    };

    let listener = prepare_listener(&config).await.expect("prepare listener");
    let permissions = std::fs::metadata(&socket_path)
        .expect("socket metadata")
        .permissions()
        .mode()
        & 0o777;

    drop(listener);

    assert_eq!(permissions, 0o600);
}

#[tokio::test]
async fn runtime_closes_idle_connections_after_timeout() {
    let tempdir = tempdir().expect("tempdir");
    let socket_path = tempdir.path().join("validation.sock");
    let config = ServerConfig {
        uds_path: socket_path.clone(),
        connection_idle_timeout: Duration::from_millis(50),
        max_connections: 16,
    };
    let listener = prepare_listener(&config).await.expect("prepare listener");
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

    let server = tokio::spawn(async move {
        serve_until(listener, config, async move {
            let _ = shutdown_rx.await;
        })
        .await
        .expect("sidecar server");
    });

    let dangerous_patterns = DEFAULT_DANGEROUS_PATTERNS
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let mut stream = UnixStream::connect(&socket_path).await.expect("connect");
    let warmup = ValidationRequest::from_raw_body(br#"{"warmup":"safe"}"#, 64, &dangerous_patterns)
        .expect("warmup request");
    let warmup_payload = encode_request_payload(&warmup).expect("warmup payload");
    write_frame(&mut stream, &warmup_payload)
        .await
        .expect("write warmup request");
    let _ = read_frame(&mut stream).await.expect("read warmup response");

    sleep(Duration::from_millis(150)).await;

    let request = ValidationRequest::from_raw_body(br#"{"name":"safe"}"#, 64, &dangerous_patterns)
        .expect("request");
    let payload = encode_request_payload(&request).expect("payload");

    let write_result = write_frame(&mut stream, &payload).await;
    let read_result = if write_result.is_ok() {
        Some(read_frame(&mut stream).await)
    } else {
        None
    };

    let _ = shutdown_tx.send(());
    server.await.expect("server join");

    assert!(
        write_result.is_err() || read_result.is_some_and(|result| result.is_err()),
        "idle connection should be closed before a response is returned"
    );
}
