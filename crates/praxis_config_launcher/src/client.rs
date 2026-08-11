use chrono::{DateTime, Utc};
use futures_util::StreamExt as _;
use reqwest::header::{ETAG, IF_MATCH, IF_NONE_MATCH};
use reqwest::{Method, Response, StatusCode};
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::artifact::{MAX_ARTIFACT_BYTES, VerifiedArtifact};
use crate::config::LauncherConfig;
use crate::error::LauncherError;
use crate::models::{DesiredResponse, ReportResponse, ReportState};
use crate::transport::AuthenticatedTransport;

const FRESHNESS_SECONDS: i64 = 3_600;

/// Result of a conditional desired-state observation.
#[derive(Clone, Debug)]
pub enum DesiredPoll {
    Modified(Box<DesiredResponse>),
    NotModified { freshness_deadline: DateTime<Utc> },
}

/// Result of an artifact request fenced by a stable directive ID.
#[derive(Clone, Debug)]
pub enum ArtifactFetch {
    Verified(Box<VerifiedArtifact>),
    DesiredChanged,
}

/// Result of a report submission, including server cursor recovery.
#[derive(Clone, Debug)]
pub enum ReportSubmission {
    Accepted(ReportResponse),
    CursorRecovered(DesiredResponse),
    DesiredChanged,
}

/// Strict HTTPS client whose identity is derived only from its credential.
#[derive(Clone, Debug)]
pub struct ArtifactClient {
    transport: AuthenticatedTransport,
}

impl ArtifactClient {
    /// Builds a client with explicit roots and all redirects disabled.
    pub async fn new(config: LauncherConfig) -> Result<Self, LauncherError> {
        let transport = AuthenticatedTransport::new(config).await?;
        Ok(Self { transport })
    }

    /// Polls desired state using only the previous response ETag.
    pub async fn poll_desired(
        &self,
        response_etag: Option<&str>,
    ) -> Result<DesiredPoll, LauncherError> {
        let response = self
            .send(
                Method::GET,
                "desired",
                response_etag.map(|value| (IF_NONE_MATCH, format!("\"{value}\""))),
                None,
            )
            .await?;
        if response.status() == StatusCode::NOT_MODIFIED {
            validate_etag(
                response.headers().get(ETAG),
                response_etag.ok_or(LauncherError::Contract("304 without a conditional ETag"))?,
            )?;
            return Ok(DesiredPoll::NotModified {
                freshness_deadline: Utc::now() + chrono::Duration::seconds(FRESHNESS_SECONDS),
            });
        }
        let response = require_success(response).await?;
        let header_etag = response.headers().get(ETAG).cloned();
        let desired: DesiredResponse = response.json().await.map_err(LauncherError::Transport)?;
        desired.validate().map_err(LauncherError::Contract)?;
        validate_etag(header_etag.as_ref(), desired.response_etag.as_str())?;
        Ok(DesiredPoll::Modified(Box::new(desired)))
    }

    /// Fetches and authenticates one canonical artifact without staging it.
    pub async fn fetch_artifact(
        &self,
        desired: &DesiredResponse,
    ) -> Result<ArtifactFetch, LauncherError> {
        if !desired.eligible
            || desired.action == crate::models::DirectiveAction::Stop
            || Utc::now() >= desired.eligibility_deadline
        {
            return Err(LauncherError::Contract(
                "desired directive is not artifact-eligible",
            ));
        }
        let response = self
            .send(
                Method::GET,
                "artifact",
                Some((IF_MATCH, desired.directive_id.as_str().to_owned())),
                None,
            )
            .await?;
        if response.status() == StatusCode::CONFLICT {
            let detail = error_detail(response).await?;
            if detail == "praxis_desired_changed" {
                let _ = self.poll_desired(None).await?;
                return Ok(ArtifactFetch::DesiredChanged);
            }
            return Err(LauncherError::Http(StatusCode::CONFLICT));
        }
        let response = require_success(response).await?;
        let expected_length = response.content_length();
        if expected_length.is_some_and(|length| length > MAX_ARTIFACT_BYTES as u64) {
            return Err(LauncherError::ArtifactTooLarge);
        }
        let expected_hash = strong_etag(response.headers().get(ETAG))?;
        let mut body = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(LauncherError::Transport)?;
            if body.len().saturating_add(chunk.len()) > MAX_ARTIFACT_BYTES {
                return Err(LauncherError::ArtifactTooLarge);
            }
            body.extend_from_slice(&chunk);
        }
        if expected_length.is_some_and(|length| length != body.len() as u64) {
            return Err(LauncherError::ArtifactTruncated);
        }
        let actual_hash = format!("{:x}", Sha256::digest(&body));
        if actual_hash != expected_hash {
            return Err(LauncherError::ArtifactHashMismatch);
        }
        Ok(ArtifactFetch::Verified(Box::new(VerifiedArtifact::verify(
            body,
            expected_hash,
            desired,
        )?)))
    }

    /// Submits the server-selected next report sequence under raw directive fencing.
    pub async fn submit_report(
        &self,
        desired: &DesiredResponse,
        state: &ReportState,
    ) -> Result<ReportSubmission, LauncherError> {
        let body = report_body(desired, state);
        let response = self
            .send(
                Method::POST,
                "reports",
                Some((IF_MATCH, desired.directive_id.as_str().to_owned())),
                Some(body),
            )
            .await?;
        if response.status() == StatusCode::CONFLICT {
            let detail = error_detail(response).await?;
            return match detail.as_str() {
                "praxis_desired_changed" => Ok(ReportSubmission::DesiredChanged),
                "praxis_report_conflict" => match self.poll_desired(None).await? {
                    DesiredPoll::Modified(current) => {
                        Ok(ReportSubmission::CursorRecovered(*current))
                    }
                    DesiredPoll::NotModified { .. } => Err(LauncherError::Contract(
                        "unconditional desired poll returned 304",
                    )),
                },
                _ => Err(LauncherError::Http(StatusCode::CONFLICT)),
            };
        }
        let response = require_success(response).await?;
        let header_etag = response.headers().get(ETAG).cloned();
        let report: ReportResponse = response.json().await.map_err(LauncherError::Transport)?;
        validate_etag(header_etag.as_ref(), report.response_etag.as_str())?;
        if report.directive_id != desired.directive_id
            || report.next_report_sequence != report.last_report_sequence.saturating_add(1)
        {
            return Err(LauncherError::Contract("report response cursor is invalid"));
        }
        Ok(ReportSubmission::Accepted(report))
    }

    async fn send(
        &self,
        method: Method,
        leaf: &str,
        conditional: Option<(reqwest::header::HeaderName, String)>,
        body: Option<serde_json::Value>,
    ) -> Result<Response, LauncherError> {
        self.transport.send(method, leaf, conditional, body).await
    }
}

fn report_body(desired: &DesiredResponse, state: &ReportState) -> serde_json::Value {
    let mut body = json!({
        "report_schema": "praxis-replica-report/v1",
        "directive_id": desired.directive_id.as_str(),
        "sequence": desired.next_report_sequence,
    });
    match state {
        ReportState::Prepared => body["state"] = json!("prepared"),
        ReportState::CanaryPassed => body["state"] = json!("canary_passed"),
        ReportState::Active => body["state"] = json!("active"),
        ReportState::Failed { failure_category } => {
            body["state"] = json!("failed");
            body["failure_category"] = json!(failure_category);
        }
    }
    body
}

async fn require_success(response: Response) -> Result<Response, LauncherError> {
    if response.status().is_success() {
        Ok(response)
    } else {
        Err(LauncherError::Http(response.status()))
    }
}

async fn error_detail(response: Response) -> Result<String, LauncherError> {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct ErrorBody {
        detail: String,
    }
    response
        .json::<ErrorBody>()
        .await
        .map(|body| body.detail)
        .map_err(LauncherError::Transport)
}

fn validate_etag(
    header: Option<&reqwest::header::HeaderValue>,
    expected: &str,
) -> Result<(), LauncherError> {
    if strong_etag(header)? == expected {
        Ok(())
    } else {
        Err(LauncherError::Contract(
            "response ETag does not match its body",
        ))
    }
}

fn strong_etag(header: Option<&reqwest::header::HeaderValue>) -> Result<String, LauncherError> {
    let value = header
        .and_then(|item| item.to_str().ok())
        .ok_or(LauncherError::Contract("strong ETag is missing"))?;
    let inner = value
        .strip_prefix('"')
        .and_then(|item| item.strip_suffix('"'))
        .ok_or(LauncherError::Contract("ETag must be quoted"))?;
    if inner.len() == 64
        && inner
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        Ok(inner.to_owned())
    } else {
        Err(LauncherError::Contract("ETag is not a lowercase SHA-256"))
    }
}
