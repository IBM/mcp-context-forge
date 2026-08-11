use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

macro_rules! validated_string {
    ($name:ident, $check:expr) => {
        #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(try_from = "String", into = "String")]
        pub struct $name(String);

        impl $name {
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl TryFrom<String> for $name {
            type Error = &'static str;

            fn try_from(value: String) -> Result<Self, Self::Error> {
                if ($check)(&value) {
                    Ok(Self(value))
                } else {
                    Err(concat!("invalid ", stringify!($name)))
                }
            }
        }

        impl From<$name> for String {
            fn from(value: $name) -> Self {
                value.0
            }
        }
    };
}

validated_string!(Sha256Hex, |value: &str| value.len() == 64
    && value
        .bytes()
        .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()));
validated_string!(SafeIdentifier, |value: &str| !value.is_empty()
    && value.len() <= 128
    && value
        .as_bytes()
        .first()
        .is_some_and(u8::is_ascii_alphanumeric)
    && value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte)));

/// Desired directive action variants from Task 11.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DirectiveAction {
    Activate,
    Retry,
    Rollback,
    Stop,
}

/// Strict desired response from `GET /praxis/v1/desired`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DesiredResponse {
    pub directive_id: Sha256Hex,
    pub response_etag: Sha256Hex,
    pub action: DirectiveAction,
    pub rollout_id: SafeIdentifier,
    pub generation_id: Option<Sha256Hex>,
    pub policy_epoch: u64,
    pub status: String,
    pub eligible: bool,
    pub eligibility_reason: Option<String>,
    pub eligibility_deadline: DateTime<Utc>,
    pub freshness_deadline: DateTime<Utc>,
    pub cohort_replica_ids: Vec<SafeIdentifier>,
    pub last_report_sequence: u64,
    pub next_report_sequence: u64,
}

impl DesiredResponse {
    pub(crate) fn validate(&self) -> Result<(), &'static str> {
        if self.next_report_sequence != self.last_report_sequence.saturating_add(1) {
            return Err("desired report cursor is invalid");
        }
        match (self.action, self.generation_id.is_some()) {
            (DirectiveAction::Stop, false)
            | (
                DirectiveAction::Activate | DirectiveAction::Retry | DirectiveAction::Rollback,
                true,
            ) => Ok(()),
            (DirectiveAction::Stop, true)
            | (
                DirectiveAction::Activate | DirectiveAction::Retry | DirectiveAction::Rollback,
                false,
            ) => Err("desired generation binding is invalid"),
        }
    }
}

/// Launcher report state accepted by Task 11.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReportState {
    Prepared,
    CanaryPassed,
    Active,
    Failed { failure_category: FailureCategory },
}

/// Sanitized Task 11 failure categories.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailureCategory {
    Spawn,
    EarlyExit,
    ConfigValidation,
    Listener,
    PolicyCanary,
    Timeout,
}

/// Strict response to `POST /praxis/v1/reports`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ReportResponse {
    pub disposition: ReportDisposition,
    pub directive_id: Sha256Hex,
    pub response_etag: Sha256Hex,
    pub last_report_sequence: u64,
    pub next_report_sequence: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ReportDisposition {
    Accepted,
    Duplicate,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractVector {
    pub vector_schema: String,
    pub input: ContractVectorInput,
    pub expected: ContractVectorExpected,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractVectorInput {
    pub compatibility: Compatibility,
    pub directive: GoldenDirective,
    pub documents: Vec<GoldenDocument>,
    pub snapshot: GoldenSnapshot,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoldenDirective {
    pub action: DirectiveAction,
    pub eligibility_deadline: DateTime<Utc>,
    pub generation_id: Sha256Hex,
    pub policy_epoch: u64,
    pub rollout_id: SafeIdentifier,
    pub target_id: SafeIdentifier,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoldenDocument {
    pub content_utf8: String,
    pub path: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GoldenSnapshot {
    pub source_fingerprint: Sha256Hex,
    pub target_id: SafeIdentifier,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Compatibility {
    pub bundle_schema: String,
    pub renderer_version: String,
    pub praxis_revision: String,
    pub cpex_contract_version: String,
    pub mcp_protocol_version: String,
    pub minimum_launcher_version: String,
}

#[derive(Debug, Deserialize)]
pub struct ContractVectorExpected {
    pub directive_id: Sha256Hex,
    #[serde(flatten)]
    pub remainder: serde_json::Value,
}
