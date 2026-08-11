mod support;

use praxis_config_launcher::artifact::MAX_ARTIFACT_BYTES;
use praxis_config_launcher::client::{ArtifactFetch, DesiredPoll};
use praxis_config_launcher::models::DesiredResponse;
use praxis_config_launcher::{ArtifactClient, LauncherConfig, LauncherError};
use serde_json::json;
use sha2::{Digest, Sha256};
use support::{MockResponse, TlsMock, canonical_archive, write_token};

const DIRECTIVE: &str = "fff66e6608eb36b8a231a7e1f22a785de294ae075e44f9dd2d4ec75dacc8ac53";
const RESPONSE_ETAG: &str = "22eca08754b347afea3f313b9db9fb3f8ca7323b6c7c359f93f6d4f1a2ba487b";

fn desired_json() -> serde_json::Value {
    json!({
        "directive_id": DIRECTIVE,
        "response_etag": RESPONSE_ETAG,
        "action": "activate",
        "rollout_id": "rollout-golden-001",
        "generation_id": "3ef9a3d9ea60f53bc440e87d7895f82d775ab15418b88044e1649b9d14e07842",
        "policy_epoch": 7,
        "status": "desired",
        "eligible": true,
        "eligibility_reason": null,
        "eligibility_deadline": "2036-08-10T12:00:00Z",
        "freshness_deadline": "2036-08-10T13:00:00Z",
        "cohort_replica_ids": ["replica-alpha"],
        "last_report_sequence": 0,
        "next_report_sequence": 1
    })
}

async fn client(mock: &TlsMock, token_path: &std::path::Path) -> ArtifactClient {
    let config =
        LauncherConfig::new(&mock.base_url, &mock.ca_path(), token_path).expect("launcher config");
    ArtifactClient::new(config).await.expect("artifact client")
}

#[tokio::test]
async fn artifact_client_polls_desired_over_trusted_tls_and_rereads_token_after_401() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "old-token");
    let mut unauthorized = MockResponse::json(401, None, json!({"detail": "unauthorized"}));
    unauthorized.rotate_token = Some((token_path.clone(), "new-token".to_owned()));
    let mock = TlsMock::start(vec![
        unauthorized,
        MockResponse::json(200, Some(RESPONSE_ETAG), desired_json()),
    ])
    .await;
    let client = client(&mock, &token_path).await;

    // When
    let result = client.poll_desired(None).await.expect("desired response");

    // Then
    assert!(matches!(result, DesiredPoll::Modified(_)));
    let requests = mock.requests.lock().expect("requests");
    assert!(requests[0].contains("authorization: Bearer old-token"));
    assert!(requests[1].contains("authorization: Bearer new-token"));
    assert!(
        requests
            .iter()
            .all(|request| !request.contains("target-alpha")
                && !request.contains("replica-alpha")
                && !request.contains("target_id")
                && !request.contains("replica_id"))
    );
    assert!(
        requests
            .iter()
            .all(|request| request.starts_with("GET /praxis/v1/desired "))
    );
}

#[tokio::test]
async fn artifact_client_verifies_hash_generation_and_compatibility_before_returning_bytes() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/praxis_config/contract-v1.json"
    ))
    .expect("golden vector");
    let archive = canonical_archive(&vector["expected"]["manifest"]);
    let hash = format!("{:x}", Sha256::digest(&archive));
    let response = MockResponse {
        status: 200,
        headers: vec![("etag".to_owned(), format!("\"{hash}\""))],
        body: archive.clone(),
        rotate_token: None,
        declared_length: None,
    };
    let mock = TlsMock::start(vec![response]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json()).expect("desired fixture");

    // When
    let result = client
        .fetch_artifact(&desired)
        .await
        .expect("verified artifact");

    // Then
    let ArtifactFetch::Verified(verified) = result else {
        panic!("expected verified artifact");
    };
    assert_eq!(verified.bytes(), archive);
    let request = &mock.requests.lock().expect("requests")[0];
    assert!(request.starts_with("GET /praxis/v1/artifact "));
    assert!(request.contains(&format!("if-match: {DIRECTIVE}")));
}

#[tokio::test]
async fn artifact_client_rejects_untrusted_ca_and_wrong_san() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let mock = TlsMock::start(vec![MockResponse::json(
        200,
        Some(RESPONSE_ETAG),
        desired_json(),
    )])
    .await;
    let invalid_ca = directory.path().join("invalid-ca.pem");
    std::fs::write(&invalid_ca, b"not a certificate").expect("invalid CA fixture");

    // When / Then
    let config = LauncherConfig::new(&mock.base_url, &invalid_ca, &token_path).expect("config");
    let invalid_result = ArtifactClient::new(config).await;
    assert!(
        matches!(invalid_result, Err(LauncherError::InvalidCaFormat)),
        "observed invalid CA result: {invalid_result:?}"
    );
    let wrong_san_url = mock.base_url.replace("localhost", "127.0.0.1");
    let config = LauncherConfig::new(&wrong_san_url, &mock.ca_path(), &token_path).expect("config");
    let wrong_san = ArtifactClient::new(config)
        .await
        .expect("client build")
        .poll_desired(None)
        .await;
    assert!(matches!(wrong_san, Err(LauncherError::Transport(_))));
}

#[tokio::test]
async fn artifact_client_rejects_bad_hash_and_oversized_body() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let bad_hash = MockResponse {
        status: 200,
        headers: vec![("etag".to_owned(), format!("\"{}\"", "0".repeat(64)))],
        body: vec![0; 1_024],
        rotate_token: None,
        declared_length: None,
    };
    let oversized = MockResponse {
        status: 200,
        headers: vec![("etag".to_owned(), format!("\"{}\"", "0".repeat(64)))],
        body: vec![0; MAX_ARTIFACT_BYTES + 1],
        rotate_token: None,
        declared_length: None,
    };
    let mock = TlsMock::start(vec![bad_hash, oversized]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json()).expect("desired fixture");

    // When / Then
    let bad_hash_result = client.fetch_artifact(&desired).await;
    assert!(
        matches!(bad_hash_result, Err(LauncherError::ArtifactHashMismatch)),
        "unexpected bad hash result: {bad_hash_result:?}"
    );
    let oversized_result = client.fetch_artifact(&desired).await;
    assert!(
        matches!(oversized_result, Err(LauncherError::ArtifactTooLarge)),
        "unexpected oversized result: {oversized_result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_truncated_body() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let body = vec![0; 1_024];
    let hash = format!("{:x}", Sha256::digest(&body));
    let truncated = MockResponse {
        status: 200,
        headers: vec![("etag".to_owned(), format!("\"{hash}\""))],
        body,
        rotate_token: None,
        declared_length: Some(2_048),
    };
    let mock = TlsMock::start(vec![truncated]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json()).expect("desired fixture");

    // When
    let result = client.fetch_artifact(&desired).await;

    // Then
    assert!(matches!(
        result,
        Err(LauncherError::ArtifactTruncated | LauncherError::Transport(_))
    ));
}
