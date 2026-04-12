// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Loopback + HMAC trust validation and Python authz callouts.
//!
//! Mirrors the MCP runtime trust model: the Rust sidecar proves identity
//! to the Python gateway via a shared-secret-derived HMAC header, and the
//! Python side performs authentication and RBAC authorization.

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::net::IpAddr;

// Header names (must match mcpgateway/main.py constants).
const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
const RUNTIME_AUTH_HEADER: &str = "x-contextforge-mcp-runtime-auth";
const AUTH_CONTEXT_HEADER: &str = "x-contextforge-auth-context";
const AUTH_CONTEXT_DERIVATION: &str = "contextforge-internal-mcp-runtime-v1";

/// Compute the HMAC trust header value from the auth secret.
///
/// Format: `SHA256("{secret}:{AUTH_CONTEXT_DERIVATION}").hex()`
pub fn compute_trust_header(
    auth_secret: &str // pragma: allowlist secret
) -> String {
    let material = format!("{auth_secret}:{AUTH_CONTEXT_DERIVATION}");
    let digest = Sha256::digest(material.as_bytes());
    digest.iter().fold(String::with_capacity(64), |mut s, b| {
        use std::fmt::Write;
        let _ = write!(s, "{b:02x}");
        s
    })
}

/// Build the standard trust headers for Rust → Python internal requests.
pub fn build_trust_headers(
    auth_secret: &str // pragma: allowlist secret
) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    headers.insert(RUNTIME_HEADER.to_string(), "rust".to_string());
    headers.insert(
        RUNTIME_AUTH_HEADER.to_string(),
        compute_trust_header(auth_secret),
    );
    headers
}

/// Encode an auth context JSON value as a base64url header value (no padding).
pub fn encode_auth_context(auth_context: &serde_json::Value) -> String {
    let json_bytes = serde_json::to_vec(auth_context).unwrap_or_default();
    URL_SAFE_NO_PAD.encode(json_bytes)
}

/// Decode a base64url-encoded auth context header back to JSON.
pub fn decode_auth_context(encoded: &str) -> Result<serde_json::Value, TrustError> {
    let bytes = URL_SAFE_NO_PAD
        .decode(encoded)
        .map_err(|e| TrustError::InvalidAuthContext(format!("base64 decode: {e}")))?;
    serde_json::from_slice(&bytes)
        .map_err(|e| TrustError::InvalidAuthContext(format!("JSON parse: {e}")))
}

/// Request body sent to `/_internal/a2a/authenticate`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateRequest {
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub query_string: String,
    pub headers: HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_ip: Option<String>,
}

/// Response from `/_internal/a2a/authenticate`.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateResponse {
    pub auth_context: serde_json::Value,
}

#[derive(Debug, thiserror::Error)]
pub enum TrustError {
    #[error("authentication failed: HTTP {status}: {detail}")]
    AuthenticationFailed { status: u16, detail: String },
    #[error("authorization denied: HTTP {status}: {detail}")]
    AuthorizationDenied { status: u16, detail: String },
    #[error("internal authz request failed: {0}")]
    RequestFailed(String),
    #[error("invalid auth context: {0}")]
    InvalidAuthContext(String),
}

/// Call `/_internal/a2a/authenticate` on the Python gateway.
///
/// Returns the raw auth context JSON on success.
pub async fn authenticate(
    client: &Client,
    backend_base_url: &str,
    auth_secret: &str, // pragma: allowlist secret
    request: &AuthenticateRequest,
) -> Result<serde_json::Value, TrustError> {
    let url = format!(
        "{}/{}",
        backend_base_url.trim_end_matches('/'),
        "_internal/a2a/authenticate"
    );

    let trust_headers = build_trust_headers(auth_secret);

    let response = client
        .post(&url)
        .headers(reqwest_headers(&trust_headers))
        .json(request)
        .send()
        .await
        .map_err(|e| TrustError::RequestFailed(e.to_string()))?;

    let status = response.status().as_u16();
    if status != 200 {
        let detail = response.text().await.unwrap_or_default();
        return Err(TrustError::AuthenticationFailed { status, detail });
    }

    let body: AuthenticateResponse = response
        .json()
        .await
        .map_err(|e| TrustError::RequestFailed(format!("invalid JSON response: {e}")))?;

    Ok(body.auth_context)
}

/// Call an `/_internal/a2a/{action}/authz` endpoint on the Python gateway.
///
/// Returns `Ok(())` on 204 (authorized) or `Err` on 403/other.
pub async fn authorize(
    client: &Client,
    backend_base_url: &str,
    auth_secret: &str, // pragma: allowlist secret
    auth_context: &serde_json::Value,
    action: &str,
) -> Result<(), TrustError> {
    let url = format!(
        "{}/_internal/a2a/{}/authz",
        backend_base_url.trim_end_matches('/'),
        action,
    );

    let mut headers = build_trust_headers(auth_secret);
    headers.insert(
        AUTH_CONTEXT_HEADER.to_string(),
        encode_auth_context(auth_context),
    );

    let response = client
        .post(&url)
        .headers(reqwest_headers(&headers))
        .send()
        .await
        .map_err(|e| TrustError::RequestFailed(e.to_string()))?;

    let status = response.status().as_u16();
    match status {
        204 => Ok(()),
        403 => {
            let detail = response.text().await.unwrap_or_default();
            Err(TrustError::AuthorizationDenied { status, detail })
        }
        _ => {
            let detail = response.text().await.unwrap_or_default();
            Err(TrustError::RequestFailed(format!(
                "unexpected authz response HTTP {status}: {detail}"
            )))
        }
    }
}

/// Validate that an inbound request to the Rust sidecar is from a trusted
/// source (loopback IP).
pub fn is_loopback(addr: Option<IpAddr>) -> bool {
    match addr {
        Some(ip) => ip.is_loopback(),
        None => false,
    }
}

/// Convert a `HashMap<String, String>` into a `reqwest::header::HeaderMap`.
pub(crate) fn reqwest_headers(map: &HashMap<String, String>) -> reqwest::header::HeaderMap {
    use reqwest::header::{HeaderName, HeaderValue};
    let mut hm = reqwest::header::HeaderMap::new();
    for (k, v) in map {
        if let (Ok(name), Ok(val)) = (
            HeaderName::from_bytes(k.as_bytes()),
            HeaderValue::from_str(v),
        ) {
            hm.insert(name, val);
        }
    }
    hm
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compute_trust_header_matches_python_format() {
        // Python: hashlib.sha256(f"{secret}:contextforge-internal-mcp-runtime-v1".encode()).hexdigest()
        let header = compute_trust_header("my-test-salt");
        assert_eq!(header.len(), 64); // SHA256 hex is 64 chars
        // Verify deterministic
        assert_eq!(header, compute_trust_header("my-test-salt"));
        // Different secret → different header
        assert_ne!(header, compute_trust_header("other-secret"));
    }

    #[test]
    fn build_trust_headers_contains_required_keys() {
        let headers = build_trust_headers("secret");
        assert_eq!(headers.get(RUNTIME_HEADER).unwrap(), "rust");
        assert!(headers.contains_key(RUNTIME_AUTH_HEADER));
    }

    #[test]
    fn encode_decode_auth_context_round_trip() {
        let ctx = serde_json::json!({
            "email": "user@example.com",
            "is_admin": false,
            "teams": ["team1"]
        });
        let encoded = encode_auth_context(&ctx);
        let decoded = decode_auth_context(&encoded).unwrap();
        assert_eq!(ctx, decoded);
    }

    #[test]
    fn decode_auth_context_rejects_invalid_base64() {
        assert!(decode_auth_context("not-valid-base64!!!").is_err());
    }

    #[test]
    fn is_loopback_accepts_127_0_0_1() {
        assert!(is_loopback(Some("127.0.0.1".parse().unwrap())));
    }

    #[test]
    fn is_loopback_accepts_ipv6_loopback() {
        assert!(is_loopback(Some("::1".parse().unwrap())));
    }

    #[test]
    fn is_loopback_rejects_external_ip() {
        assert!(!is_loopback(Some("203.0.113.42".parse().unwrap())));
    }

    #[test]
    fn is_loopback_rejects_none() {
        assert!(!is_loopback(None));
    }
}
