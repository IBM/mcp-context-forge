mod support;

use praxis_config_launcher::client::{DesiredPoll, ReportSubmission};
use praxis_config_launcher::models::{DesiredResponse, ReportState};
use praxis_config_launcher::{ArtifactClient, LauncherConfig, LauncherError};
use serde_json::json;
use sha2::Digest as _;
use support::{MockResponse, TlsMock, canonical_archive, write_token};

const DIRECTIVE: &str = "fff66e6608eb36b8a231a7e1f22a785de294ae075e44f9dd2d4ec75dacc8ac53";
const RESPONSE_ETAG: &str = "22eca08754b347afea3f313b9db9fb3f8ca7323b6c7c359f93f6d4f1a2ba487b";

fn desired_json(last: u64, next: u64) -> serde_json::Value {
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
        "last_report_sequence": last,
        "next_report_sequence": next
    })
}

async fn client(mock: &TlsMock, token_path: &std::path::Path) -> ArtifactClient {
    let config =
        LauncherConfig::new(&mock.base_url, &mock.ca_path(), token_path).expect("launcher config");
    ArtifactClient::new(config).await.expect("artifact client")
}

fn accepted_report() -> serde_json::Value {
    json!({
        "disposition": "accepted",
        "directive_id": DIRECTIVE,
        "response_etag": RESPONSE_ETAG,
        "last_report_sequence": 1,
        "next_report_sequence": 2
    })
}

async fn submit_report_with_headers(
    headers: Vec<(String, String)>,
) -> Result<ReportSubmission, LauncherError> {
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let response = MockResponse {
        status: 200,
        headers,
        body: serde_json::to_vec(&accepted_report()).expect("report JSON"),
        rotate_token: None,
        declared_length: None,
    };
    let mock = TlsMock::start(vec![response]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json(0, 1)).expect("desired");
    client.submit_report(&desired, &ReportState::Prepared).await
}

#[tokio::test]
async fn artifact_client_handles_304_freshness_without_reusing_directive_as_etag() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let response = MockResponse {
        status: 304,
        headers: vec![("etag".to_owned(), format!("\"{RESPONSE_ETAG}\""))],
        body: Vec::new(),
        rotate_token: None,
        declared_length: None,
    };
    let mock = TlsMock::start(vec![response]).await;
    let client = client(&mock, &token_path).await;

    // When
    let result = client
        .poll_desired(Some(RESPONSE_ETAG))
        .await
        .expect("304 freshness");

    // Then
    assert!(matches!(result, DesiredPoll::NotModified { .. }));
    let request = &mock.requests.lock().expect("requests")[0];
    assert!(request.contains(&format!("if-none-match: \"{RESPONSE_ETAG}\"")));
    assert!(!request.contains(&format!("if-none-match: \"{DIRECTIVE}\"")));
}

#[tokio::test]
async fn artifact_client_recovers_report_cursor_from_server_after_conflict() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let conflict = MockResponse::json(409, None, json!({"detail": "praxis_report_conflict"}));
    let current = MockResponse::json(200, Some(RESPONSE_ETAG), desired_json(4, 5));
    let mock = TlsMock::start(vec![conflict, current]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json(0, 1)).expect("desired");

    // When
    let result = client
        .submit_report(&desired, &ReportState::Prepared)
        .await
        .expect("cursor recovery");

    // Then
    let ReportSubmission::CursorRecovered(recovered) = result else {
        panic!("expected recovered cursor");
    };
    assert_eq!(
        (
            recovered.last_report_sequence,
            recovered.next_report_sequence
        ),
        (4, 5)
    );
    let requests = mock.requests.lock().expect("requests");
    assert!(requests[0].starts_with("POST /praxis/v1/reports "));
    assert!(requests[0].contains(&format!("if-match: {DIRECTIVE}")));
    assert!(requests[0].contains("\"sequence\":1"));
    assert!(requests[1].starts_with("GET /praxis/v1/desired "));
}

#[tokio::test]
async fn artifact_client_accepts_report_when_strong_etag_matches_body() {
    // Given / When
    let result =
        submit_report_with_headers(vec![("etag".to_owned(), format!("\"{RESPONSE_ETAG}\""))]).await;

    // Then
    assert!(
        matches!(result, Ok(ReportSubmission::Accepted(_))),
        "unexpected accepted report result: {result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_report_when_etag_is_missing() {
    // Given / When
    let result = submit_report_with_headers(Vec::new()).await;

    // Then
    assert!(
        matches!(result, Err(LauncherError::Contract(_))),
        "unexpected missing ETag result: {result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_report_when_etag_is_weak() {
    // Given / When
    let result =
        submit_report_with_headers(vec![("etag".to_owned(), format!("W/\"{RESPONSE_ETAG}\""))])
            .await;

    // Then
    assert!(
        matches!(result, Err(LauncherError::Contract(_))),
        "unexpected weak ETag result: {result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_report_when_etag_is_malformed() {
    // Given / When
    let result =
        submit_report_with_headers(vec![("etag".to_owned(), "\"not-a-sha256\"".to_owned())]).await;

    // Then
    assert!(
        matches!(result, Err(LauncherError::Contract(_))),
        "unexpected malformed ETag result: {result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_report_when_etag_mismatches_body() {
    // Given / When
    let result =
        submit_report_with_headers(vec![("etag".to_owned(), format!("\"{}\"", "0".repeat(64)))])
            .await;

    // Then
    assert!(
        matches!(result, Err(LauncherError::Contract(_))),
        "unexpected mismatched ETag result: {result:?}"
    );
}

#[tokio::test]
async fn artifact_client_rejects_cross_host_redirect_and_incompatible_manifest() {
    // Given
    let directory = tempfile::tempdir().expect("tempdir");
    let token_path = write_token(&directory, "token");
    let redirect = MockResponse {
        status: 302,
        headers: vec![(
            "location".to_owned(),
            "https://attacker.test/praxis/v1/desired".to_owned(),
        )],
        body: Vec::new(),
        rotate_token: None,
        declared_length: None,
    };
    let vector: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/praxis_config/contract-v1.json"
    ))
    .expect("golden vector");
    let mut manifest = vector["expected"]["manifest"].clone();
    manifest["mcp_protocol_version"] = json!("unsupported");
    let archive = canonical_archive(&manifest);
    let hash = format!("{:x}", sha2::Sha256::digest(&archive));
    let incompatible = MockResponse {
        status: 200,
        headers: vec![("etag".to_owned(), format!("\"{hash}\""))],
        body: archive,
        rotate_token: None,
        declared_length: None,
    };
    let mock = TlsMock::start(vec![redirect, incompatible]).await;
    let client = client(&mock, &token_path).await;
    let desired: DesiredResponse = serde_json::from_value(desired_json(0, 1)).expect("desired");

    // When / Then
    assert!(
        matches!(client.poll_desired(None).await, Err(LauncherError::Http(status)) if status.as_u16() == 302)
    );
    assert!(matches!(
        client.fetch_artifact(&desired).await,
        Err(LauncherError::Incompatible(_))
    ));
}
