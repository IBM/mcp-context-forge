// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Request/response DTOs for the A2A runtime invoke API.

use crate::errors::InvokeError;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Request DTOs
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InvokeRequestDto {
    /// Index for ordering results in a batch.
    #[serde(default)]
    pub id: usize,
    /// Target agent endpoint URL (without auth query params applied).
    pub endpoint_url: String,
    /// JSON body to POST to the agent.
    pub json_body: serde_json::Value,
    /// Base headers (without decrypted auth headers).
    #[serde(default)]
    pub headers: HashMap<String, String>,
    /// Per-request timeout override in seconds.
    pub timeout_seconds: Option<u64>,
    /// Encrypted auth header blob (decrypted by Rust when auth_secret is set).
    pub auth_headers_encrypted: Option<String>,
    /// Encrypted query param auth blobs (each value decrypted independently).
    pub auth_query_params_encrypted: Option<HashMap<String, String>>,
    /// Distributed tracing: correlation ID.
    pub correlation_id: Option<String>,
    /// Distributed tracing: W3C traceparent.
    pub traceparent: Option<String>,
    /// Agent name for logging/metrics.
    pub agent_name: Option<String>,
    /// Agent ID for metrics recording.
    pub agent_id: Option<String>,
    /// Interaction type for metrics.
    pub interaction_type: Option<String>,
    /// Tenant/team scope for circuit breaker isolation.
    pub scope_id: Option<String>,
    /// Idempotency key for request coalescing.
    pub request_id: Option<String>,
}

// ---------------------------------------------------------------------------
// Response DTOs
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
pub struct InvokeResultDto {
    pub id: usize,
    pub status_code: u16,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub json: Option<serde_json::Value>,
    pub text: String,
    pub headers: HashMap<String, String>,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    pub duration_secs: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub agent_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct MetricRowDto {
    pub agent_id: String,
    pub response_time: f64,
    pub is_success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub interaction_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
}

// ---------------------------------------------------------------------------
// Resolved request (post-decryption)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ResolvedRequest {
    pub id: usize,
    pub endpoint_url: String,
    pub headers: HashMap<String, String>,
    pub json_body: serde_json::Value,
    pub timeout_seconds: Option<u64>,
    pub agent_name: Option<String>,
    pub agent_id: Option<String>,
    pub interaction_type: Option<String>,
    pub scope_id: Option<String>,
    pub request_id: Option<String>,
    pub correlation_id: Option<String>,
}

// ---------------------------------------------------------------------------
// Resolution logic
// ---------------------------------------------------------------------------

/// Parse raw DTOs into resolved invoke requests.
///
/// When `auth_secret` is `Some`, encrypted auth fields are decrypted
/// and merged into the URL/headers.  When `auth_secret` is `None` and
/// encrypted fields are present, returns an error.
pub fn resolve_requests(
    requests: &[InvokeRequestDto],
    auth_secret: Option<&str>, // pragma: allowlist secret
) -> Result<Vec<ResolvedRequest>, InvokeError> {
    let mut resolved = Vec::with_capacity(requests.len());

    for req in requests {
        let has_encrypted =
            req.auth_headers_encrypted.is_some() || req.auth_query_params_encrypted.is_some();

        if has_encrypted && auth_secret.is_none() {
            return Err(InvokeError::Auth(
                "encrypted auth fields present but no auth_secret configured".to_string(),
            ));
        }

        let mut headers = req.headers.clone();
        let mut endpoint_url = req.endpoint_url.clone();

        // Decrypt and merge auth headers.
        let decrypted_headers = match (&req.auth_headers_encrypted, auth_secret) {
            (Some(blob), Some(secret)) => {
                let decrypted = crate::auth::decrypt_auth(blob, secret); // pragma: allowlist secret
                Some(decrypted.map_err(|e| {
                    InvokeError::Auth(format!("auth header decryption failed: {e}"))
                })?)
            }
            _ => None,
        };

        // Decrypt and merge auth query params.
        let decrypted_params = match (&req.auth_query_params_encrypted, auth_secret) {
            (Some(map), Some(secret)) => {
                let decrypted = crate::auth::decrypt_map_values(map, secret); // pragma: allowlist secret
                Some(decrypted.map_err(|e| {
                    InvokeError::Auth(format!("auth query param decryption failed: {e}"))
                })?)
            }
            _ => None,
        };

        // Apply auth to URL and headers.
        if decrypted_headers.is_some() || decrypted_params.is_some() {
            let params = decrypted_params.unwrap_or_default();
            #[rustfmt::skip]
            let applied = crate::auth::apply_invoke_auth(&endpoint_url, &params, &mut headers, decrypted_headers.as_ref()); // pragma: allowlist secret
            endpoint_url =
                applied.map_err(|e| InvokeError::Auth(format!("apply_invoke_auth failed: {e}")))?;
        }

        // Inject tracing headers.
        if let Some(ref cid) = req.correlation_id {
            headers
                .entry("x-correlation-id".to_string())
                .or_insert_with(|| cid.clone());
        }
        if let Some(ref tp) = req.traceparent {
            headers
                .entry("traceparent".to_string())
                .or_insert_with(|| tp.clone());
        }

        // Default Content-Type.
        if !headers
            .keys()
            .any(|k| k.eq_ignore_ascii_case("content-type"))
        {
            headers.insert("content-type".to_string(), "application/json".to_string());
        }

        resolved.push(ResolvedRequest {
            id: req.id,
            endpoint_url,
            headers,
            json_body: req.json_body.clone(),
            timeout_seconds: req.timeout_seconds,
            agent_name: req.agent_name.clone(),
            agent_id: req.agent_id.clone(),
            interaction_type: req.interaction_type.clone(),
            scope_id: req.scope_id.clone(),
            request_id: req.request_id.clone(),
            correlation_id: req.correlation_id.clone(),
        });
    }

    Ok(resolved)
}

// ---------------------------------------------------------------------------
// Result builder
// ---------------------------------------------------------------------------

/// Convert invoke results into response DTOs.
pub fn build_result_dto(
    id: usize,
    result: &Result<crate::invoke::InvokeResult, InvokeError>,
    duration: std::time::Duration,
    agent_name: Option<&str>,
) -> InvokeResultDto {
    match result {
        Ok(inv) => {
            let success = (200..300).contains(&inv.status_code);
            InvokeResultDto {
                id,
                status_code: inv.status_code,
                json: inv.json.clone(),
                text: inv.text.clone(),
                headers: inv.headers.clone(),
                success,
                error: None,
                code: None,
                duration_secs: duration.as_secs_f64(),
                agent_name: agent_name.map(String::from),
                session_id: None,
            }
        }
        Err(err) => InvokeResultDto {
            id,
            status_code: err.http_status().as_u16(),
            json: None,
            text: String::new(),
            headers: HashMap::new(),
            success: false,
            error: Some(err.to_string()),
            code: Some(err.error_code().to_string()),
            duration_secs: duration.as_secs_f64(),
            agent_name: agent_name.map(String::from),
            session_id: None,
        },
    }
}

// ---------------------------------------------------------------------------
// Agent resolution (from Python /_internal/a2a/agents/{name}/resolve)
// ---------------------------------------------------------------------------

/// Deserialized response from the Python agent resolve endpoint.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ResolvedAgent {
    pub agent_id: String,
    pub name: String,
    pub endpoint_url: String,
    #[serde(default)]
    pub agent_type: Option<String>,
    #[serde(default)]
    pub protocol_version: Option<String>,
    #[serde(default)]
    pub auth_type: Option<String>,
    #[serde(default)]
    pub auth_value_encrypted: Option<String>,
    #[serde(default)]
    pub auth_query_params_encrypted: Option<HashMap<String, String>>,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::invoke::InvokeResult;
    use aes_gcm::AeadCore;
    use aes_gcm::aead::{Aead, OsRng};
    use aes_gcm::{Aes256Gcm, KeyInit};
    use base64::engine::{Engine, general_purpose::URL_SAFE_NO_PAD};
    use sha2::{Digest, Sha256};
    use std::time::Duration;

    fn minimal_dto(endpoint_url: &str) -> InvokeRequestDto {
        InvokeRequestDto {
            id: 0,
            endpoint_url: endpoint_url.to_string(),
            json_body: serde_json::json!({"msg": "hello"}),
            headers: HashMap::new(),
            timeout_seconds: None,
            auth_headers_encrypted: None,
            auth_query_params_encrypted: None,
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
        }
    }

    fn encrypt_map(
        payload: &HashMap<String, String>,
        secret: &str, /* pragma: allowlist secret */
    ) -> String {
        let plaintext = serde_json::to_vec(payload).unwrap();
        let mut hasher = Sha256::new();
        hasher.update(secret.as_bytes());
        let key: [u8; 32] = hasher.finalize().into();
        let cipher = Aes256Gcm::new(&key.into());
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = cipher.encrypt(&nonce, plaintext.as_ref()).unwrap();
        let mut combined = nonce.to_vec();
        combined.extend_from_slice(&ciphertext);
        URL_SAFE_NO_PAD.encode(combined)
    }

    #[test]
    fn resolve_no_encrypted_fields_passes_through() {
        let reqs = vec![minimal_dto("https://agent.example.com/invoke")];
        let resolved = resolve_requests(&reqs, None).unwrap();
        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].endpoint_url, "https://agent.example.com/invoke");
        assert!(resolved[0].headers.contains_key("content-type"));
    }

    #[test]
    fn resolve_encrypted_fields_without_secret_returns_auth_error() {
        let mut dto = minimal_dto("https://agent.example.com/invoke");
        dto.auth_headers_encrypted = Some("some-blob".to_string());

        let err = resolve_requests(&[dto], None).unwrap_err();
        assert!(matches!(err, InvokeError::Auth(_)));
        assert!(err.to_string().contains("no auth_secret configured"));
    }

    #[test]
    fn build_result_dto_from_success() {
        let result = Ok(InvokeResult {
            status_code: 200,
            headers: HashMap::new(),
            json: Some(serde_json::json!({"ok": true})),
            text: r#"{"ok":true}"#.to_string(),
        });
        let dto = build_result_dto(7, &result, Duration::from_millis(150), Some("echo"));
        assert_eq!(dto.id, 7);
        assert_eq!(dto.status_code, 200);
        assert!(dto.success);
        assert!(dto.error.is_none());
        assert!(dto.code.is_none());
        assert_eq!(dto.agent_name.as_deref(), Some("echo"));
        assert!(dto.duration_secs > 0.0);
    }

    #[test]
    fn build_result_dto_from_error() {
        let result: Result<InvokeResult, InvokeError> =
            Err(InvokeError::Timeout(Duration::from_secs(30)));
        let dto = build_result_dto(3, &result, Duration::from_secs(30), None);
        assert_eq!(dto.id, 3);
        assert!(!dto.success);
        assert!(dto.error.is_some());
        assert_eq!(dto.code.as_deref(), Some("timeout"));
        assert!(dto.agent_name.is_none());
    }

    #[test]
    fn correlation_id_and_traceparent_added_to_headers() {
        let mut dto = minimal_dto("https://agent.example.com/invoke");
        dto.correlation_id = Some("corr-123".to_string());
        dto.traceparent = Some("00-abc-def-01".to_string());

        let resolved = resolve_requests(&[dto], None).unwrap();
        assert_eq!(
            resolved[0].headers.get("x-correlation-id").unwrap(),
            "corr-123"
        );
        assert_eq!(
            resolved[0].headers.get("traceparent").unwrap(),
            "00-abc-def-01"
        );
    }

    #[test]
    fn content_type_defaults_to_json() {
        let dto = minimal_dto("https://agent.example.com/invoke");
        let resolved = resolve_requests(&[dto], None).unwrap();
        assert_eq!(
            resolved[0].headers.get("content-type").unwrap(),
            "application/json"
        );
    }

    #[test]
    fn content_type_not_overwritten_when_present() {
        let mut dto = minimal_dto("https://agent.example.com/invoke");
        dto.headers
            .insert("Content-Type".to_string(), "text/plain".to_string());

        let resolved = resolve_requests(&[dto], None).unwrap();
        assert_eq!(
            resolved[0].headers.get("Content-Type").unwrap(),
            "text/plain"
        );
        // Should not have a duplicate lowercase key.
        assert!(!resolved[0].headers.contains_key("content-type"));
    }

    #[test]
    fn correlation_headers_do_not_override_existing_values() {
        let mut dto = minimal_dto("https://agent.example.com/invoke");
        dto.headers.insert(
            "x-correlation-id".to_string(),
            "existing-correlation".to_string(),
        );
        dto.headers.insert(
            "traceparent".to_string(),
            "existing-traceparent".to_string(),
        );
        dto.correlation_id = Some("new-correlation".to_string());
        dto.traceparent = Some("00-new-parent".to_string());

        let resolved = resolve_requests(&[dto], None).unwrap();
        assert_eq!(
            resolved[0].headers.get("x-correlation-id").unwrap(),
            "existing-correlation"
        );
        assert_eq!(
            resolved[0].headers.get("traceparent").unwrap(),
            "existing-traceparent"
        );
    }

    #[test]
    fn resolve_requests_preserves_request_metadata_fields() {
        let mut dto = minimal_dto("https://agent.example.com/invoke");
        dto.id = 42;
        dto.timeout_seconds = Some(9);
        dto.agent_name = Some("demo-agent".to_string());
        dto.agent_id = Some("agent-123".to_string());
        dto.interaction_type = Some("query".to_string());
        dto.scope_id = Some("team-a".to_string());
        dto.request_id = Some("req-1".to_string());
        dto.correlation_id = Some("corr-1".to_string());

        let resolved = resolve_requests(&[dto], None).unwrap();
        assert_eq!(resolved[0].id, 42);
        assert_eq!(resolved[0].timeout_seconds, Some(9));
        assert_eq!(resolved[0].agent_name.as_deref(), Some("demo-agent"));
        assert_eq!(resolved[0].agent_id.as_deref(), Some("agent-123"));
        assert_eq!(resolved[0].interaction_type.as_deref(), Some("query"));
        assert_eq!(resolved[0].scope_id.as_deref(), Some("team-a"));
        assert_eq!(resolved[0].request_id.as_deref(), Some("req-1"));
        assert_eq!(resolved[0].correlation_id.as_deref(), Some("corr-1"));
    }

    #[test]
    fn resolve_requests_decrypts_auth_and_applies_to_url_and_headers() {
        let secret = "secret-123"; // pragma: allowlist secret
        let mut dto = minimal_dto("https://agent.example.com/invoke?existing=1");
        dto.auth_headers_encrypted = Some(encrypt_map(
            &HashMap::from([("authorization".to_string(), "Bearer token".to_string())]),
            secret,
        ));
        dto.auth_query_params_encrypted = Some(HashMap::from([(
            "api_key".to_string(),
            encrypt_map(
                &HashMap::from([("api_key".to_string(), "secret".to_string())]),
                secret,
            ),
        )]));

        let resolved = resolve_requests(&[dto], Some(secret)).unwrap();
        assert_eq!(
            resolved[0].headers.get("authorization").map(String::as_str),
            Some("Bearer token")
        );
        assert!(resolved[0].endpoint_url.contains("existing=1"));
        assert!(
            resolved[0].endpoint_url.contains("api_key=secret"), // pragma: allowlist secret
            "expected decrypted auth query param to be applied"
        );
    }

    #[test]
    fn resolve_requests_surfaces_header_and_query_decrypt_failures() {
        let mut bad_header = minimal_dto("https://agent.example.com/invoke");
        bad_header.auth_headers_encrypted = Some("not-valid".to_string());
        let err = resolve_requests(&[bad_header], Some("secret")).unwrap_err();
        assert!(err.to_string().contains("auth header decryption failed"));

        let mut bad_query = minimal_dto("https://agent.example.com/invoke");
        bad_query.auth_query_params_encrypted = Some(HashMap::from([(
            "token".to_string(),
            "not-valid".to_string(),
        )]));
        let err = resolve_requests(&[bad_query], Some("secret")).unwrap_err();
        assert!(
            err.to_string()
                .contains("auth query param decryption failed")
        );
    }

    #[test]
    fn resolve_requests_surfaces_apply_auth_failures() {
        let secret = "secret-123"; // pragma: allowlist secret
        let mut dto = minimal_dto("file:///tmp/socket");
        dto.auth_query_params_encrypted = Some(HashMap::from([(
            "api_key".to_string(),
            encrypt_map(
                &HashMap::from([("api_key".to_string(), "secret".to_string())]),
                secret,
            ),
        )]));

        let err = resolve_requests(&[dto], Some(secret)).unwrap_err();
        assert!(err.to_string().contains("apply_invoke_auth failed"));
    }
}
