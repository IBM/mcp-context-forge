// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! AES-GCM auth decryption matching Python services_auth contract.

use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
use base64::engine::{Engine, general_purpose::URL_SAFE_NO_PAD};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use url::Url;

/// Minimum ciphertext length: 12-byte nonce + at least 1 byte of
/// ciphertext/tag data.
const MIN_BLOB_LEN: usize = 13;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("base64 decode failed: {0}")]
    Base64(String),
    #[error("ciphertext too short (need at least 13 bytes for nonce + 1 byte data)")]
    TooShort,
    #[error("AES-GCM decryption failed")]
    Decrypt,
    #[error("decrypted payload is not valid UTF-8: {0}")]
    Utf8(String),
    #[error("decrypted payload is not valid JSON: {0}")]
    Json(String),
    #[error("invalid URL scheme: {0}")]
    InvalidScheme(String),
    #[error("invalid URL: {0}")]
    InvalidUrl(String),
}

// ---------------------------------------------------------------------------
// Core helpers
// ---------------------------------------------------------------------------

/// Derive a 256-bit AES key from the raw bytes of `secret`.
#[rustfmt::skip]
fn derive_key(secret: &str) -> [u8; 32] { // pragma: allowlist secret
    let mut hasher = Sha256::new();
    hasher.update(secret.as_bytes());
    hasher.finalize().into()
}

/// Build an `Aes256Gcm` cipher from a secret string.
#[rustfmt::skip]
fn cipher_for(secret: &str) -> Aes256Gcm { // pragma: allowlist secret
    Aes256Gcm::new(&derive_key(secret).into())
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Encrypt an auth map with the same scheme `decrypt_auth` consumes.
///
/// Test helper that mirrors Python `services_auth.encode_auth` so
/// integration tests can exercise the /invoke decryption path end-to-end
/// without round-tripping through the Python gateway.  Always available
/// (not gated on `#[cfg(test)]`) because Cargo integration-test targets
/// link against the library crate's non-test build.
///
/// Uses a nanosecond-derived nonce: unique enough for tests, and nonce
/// uniqueness only matters per-key; production paths never call this.
#[doc(hidden)]
pub fn encrypt_auth_for_tests(
    value: &HashMap<String, String>,
    secret: &str, // pragma: allowlist secret
) -> String {
    use aes_gcm::aead::Aead;
    use std::time::{SystemTime, UNIX_EPOCH};

    let json_bytes = serde_json::to_vec(value).expect("auth map is serializable");
    // 96-bit nonce derived from the current nanosecond count.  Good enough
    // for per-test uniqueness; never reused within a test process.
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mut nonce_bytes = [0u8; 12];
    nonce_bytes[..8].copy_from_slice(&(nanos as u64).to_le_bytes());
    nonce_bytes[8..].copy_from_slice(&((nanos >> 64) as u32).to_le_bytes());
    let nonce = Nonce::from_slice(&nonce_bytes);
    let ciphertext = cipher_for(secret)
        .encrypt(nonce, json_bytes.as_ref())
        .expect("encryption never fails for in-memory payload");
    let mut combined = Vec::with_capacity(12 + ciphertext.len());
    combined.extend_from_slice(&nonce_bytes);
    combined.extend_from_slice(&ciphertext);
    URL_SAFE_NO_PAD.encode(combined)
}

/// Decrypt a single base64url-encoded AES-GCM ciphertext.
///
/// The blob format (produced by Python `encode_auth`) is:
///
/// ```text
/// base64url_no_pad(nonce_12 || ciphertext_with_tag)
/// ```
///
/// Returns the parsed JSON payload as a `HashMap<String, String>`.
pub fn decrypt_auth(
    ciphertext_b64: &str,
    secret: &str, // pragma: allowlist secret
) -> Result<HashMap<String, String>, AuthError> {
    let combined = URL_SAFE_NO_PAD
        .decode(ciphertext_b64)
        .map_err(|e| AuthError::Base64(e.to_string()))?;

    if combined.len() < MIN_BLOB_LEN {
        return Err(AuthError::TooShort);
    }

    let (nonce_bytes, ciphertext) = combined.split_at(12);
    let nonce = Nonce::from_slice(nonce_bytes);

    let plaintext = cipher_for(secret)
        .decrypt(nonce, ciphertext)
        .map_err(|_| AuthError::Decrypt)?;

    let json_str = std::str::from_utf8(&plaintext).map_err(|e| AuthError::Utf8(e.to_string()))?;

    serde_json::from_str(json_str).map_err(|e| AuthError::Json(e.to_string()))
}

/// Batch-decrypt map values: each value is independently encrypted.
///
/// For every `(param_name, encrypted_blob)` pair in `map`, the blob is
/// decrypted to a `HashMap<String, String>`.  The entry whose key matches
/// `param_name` is extracted into the result.
pub fn decrypt_map_values(
    map: &HashMap<String, String>,
    secret: &str, // pragma: allowlist secret
) -> Result<HashMap<String, String>, AuthError> {
    let mut result = HashMap::with_capacity(map.len());
    for (param_name, encrypted_blob) in map {
        let decrypted = decrypt_auth(encrypted_blob, secret)?;
        if let Some(value) = decrypted.get(param_name) {
            result.insert(param_name.clone(), value.clone());
        }
    }
    Ok(result)
}

/// Apply decrypted auth to a URL and headers.
///
/// * Merges `query_params` into the URL query string (auth params override
///   any existing params with the same key).
/// * If `header_auth` is `Some`, merges those entries into `headers`.
/// * Validates that the URL scheme is `http` or `https`.
///
/// Returns the (possibly modified) URL as a string.
pub fn apply_invoke_auth(
    endpoint_url: &str,
    query_params: &HashMap<String, String>,
    headers: &mut HashMap<String, String>,
    header_auth: Option<&HashMap<String, String>>, // pragma: allowlist secret
) -> Result<String, AuthError> {
    let mut url = Url::parse(endpoint_url).map_err(|e| AuthError::InvalidUrl(e.to_string()))?;

    match url.scheme() {
        "http" | "https" => {}
        other => return Err(AuthError::InvalidScheme(other.to_owned())),
    }

    // Merge auth query params (override existing keys).
    //
    // Use BTreeMap so the resulting query string is lexicographically
    // ordered.  HashMap iteration order is randomized per-process, which
    // would (a) break HMAC/signed-URL flows that require a canonical
    // serialization and (b) make log/diff comparison non-deterministic.
    if !query_params.is_empty() {
        let mut merged: std::collections::BTreeMap<String, String> = url
            .query_pairs()
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();
        merged.extend(query_params.iter().map(|(k, v)| (k.clone(), v.clone())));

        url.query_pairs_mut().clear().extend_pairs(merged.iter());
    }

    // Merge header auth.
    if let Some(ha) = header_auth {
        for (k, v) in ha {
            headers.insert(k.clone(), v.clone());
        }
    }

    Ok(url.to_string())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use aes_gcm::AeadCore;
    use aes_gcm::aead::OsRng;

    /// Test-only encrypt helper that mirrors the Python `encode_auth`.
    fn encrypt_auth(
        payload: &HashMap<String, String>,
        secret: &str, /* pragma: allowlist secret */
    ) -> String {
        let plaintext = serde_json::to_vec(payload).unwrap();
        let cipher = cipher_for(secret);
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = cipher.encrypt(&nonce, plaintext.as_ref()).unwrap();
        let mut combined = nonce.to_vec();
        combined.extend_from_slice(&ciphertext);
        URL_SAFE_NO_PAD.encode(&combined)
    }

    #[test]
    fn round_trip_encrypt_decrypt() {
        let secret = "test-secret-42"; // pragma: allowlist secret
        let mut payload = HashMap::new();
        payload.insert("user".to_string(), "alice".to_string());
        payload.insert("token".to_string(), "abc123".to_string());

        let encrypted = encrypt_auth(&payload, secret);
        let decrypted = decrypt_auth(&encrypted, secret).unwrap();
        assert_eq!(decrypted, payload);
    }

    #[test]
    fn decrypt_wrong_secret_fails() {
        let mut payload = HashMap::new();
        payload.insert("key".to_string(), "value".to_string());
        let encrypted = encrypt_auth(&payload, "correct-secret");

        let result = decrypt_auth(&encrypted, "wrong-secret");
        assert!(
            matches!(result, Err(AuthError::Decrypt)),
            "expected Decrypt error, got {result:?}"
        );
    }

    #[test]
    fn decrypt_invalid_base64_fails() {
        let result = decrypt_auth("!!!not-base64!!!", "secret");
        assert!(
            matches!(result, Err(AuthError::Base64(_))),
            "expected Base64 error, got {result:?}"
        );
    }

    #[test]
    fn decrypt_too_short_blob_fails() {
        // 8 bytes of data -> base64 encodes to 11 chars (no pad)
        let short = URL_SAFE_NO_PAD.encode([0u8; 8]);
        let result = decrypt_auth(&short, "secret");
        assert!(
            matches!(result, Err(AuthError::TooShort)),
            "expected TooShort error, got {result:?}"
        );
    }

    fn encrypt_raw_payload(plaintext: &[u8], key_material: &str) -> String {
        let cipher = cipher_for(key_material);
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = cipher.encrypt(&nonce, plaintext).unwrap();
        let mut combined = nonce.to_vec();
        combined.extend_from_slice(&ciphertext);
        URL_SAFE_NO_PAD.encode(&combined)
    }

    #[test]
    fn decrypt_rejects_non_utf8_plaintext() {
        let encrypted = encrypt_raw_payload(&[0xf0, 0x28, 0x8c, 0x28], "utf8-secret");
        let result = decrypt_auth(&encrypted, "utf8-secret");
        assert!(
            matches!(result, Err(AuthError::Utf8(_))),
            "expected Utf8 error, got {result:?}"
        );
    }

    #[test]
    fn decrypt_rejects_non_json_plaintext() {
        let encrypted = encrypt_raw_payload(br#"not-json"#, "json-secret");
        let result = decrypt_auth(&encrypted, "json-secret");
        assert!(
            matches!(result, Err(AuthError::Json(_))),
            "expected Json error, got {result:?}"
        );
    }

    #[test]
    fn apply_invoke_auth_rejects_file_scheme() {
        let mut headers = HashMap::new();
        let params = HashMap::new();
        let result = apply_invoke_auth("file:///etc/passwd", &params, &mut headers, None);
        assert!(
            matches!(result, Err(AuthError::InvalidScheme(ref s)) if s == "file"),
            "expected InvalidScheme(file), got {result:?}"
        );
    }

    #[test]
    fn apply_invoke_auth_merges_query_params() {
        let mut headers = HashMap::new();
        let mut params = HashMap::new();
        params.insert("api_key".to_string(), "secret123".to_string());

        let url = apply_invoke_auth(
            "https://example.com/api?existing=1",
            &params,
            &mut headers,
            None,
        )
        .unwrap();

        let parsed = Url::parse(&url).unwrap();
        let pairs: HashMap<String, String> = parsed
            .query_pairs()
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();

        assert_eq!(pairs.get("api_key").unwrap(), "secret123");
        assert_eq!(pairs.get("existing").unwrap(), "1");
    }

    #[test]
    fn apply_invoke_auth_overrides_existing_query_param() {
        let mut headers = HashMap::new();
        let mut params = HashMap::new();
        params.insert("key".to_string(), "new_value".to_string());

        let url = apply_invoke_auth(
            "https://example.com/api?key=old_value",
            &params,
            &mut headers,
            None,
        )
        .unwrap();

        let parsed = Url::parse(&url).unwrap();
        let pairs: HashMap<String, String> = parsed
            .query_pairs()
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();

        assert_eq!(pairs.get("key").unwrap(), "new_value");
    }

    #[test]
    fn apply_invoke_auth_merges_header_auth() {
        let mut headers = HashMap::new();
        headers.insert("Content-Type".to_string(), "application/json".to_string());

        let mut header_auth = HashMap::new();
        header_auth.insert("Authorization".to_string(), "Bearer tok123".to_string());

        let _url = apply_invoke_auth(
            "https://example.com/api",
            &HashMap::new(),
            &mut headers,
            Some(&header_auth),
        )
        .unwrap();

        assert_eq!(headers.get("Authorization").unwrap(), "Bearer tok123");
        // Original header preserved.
        assert_eq!(headers.get("Content-Type").unwrap(), "application/json");
    }

    #[test]
    fn decrypt_map_values_extracts_matching_keys() {
        let secret = "map-secret"; // pragma: allowlist secret

        // Each map value is an independently encrypted blob whose plaintext
        // JSON contains the key matching the map key.
        let mut api_key_payload = HashMap::new();
        api_key_payload.insert("api_key".to_string(), "k-12345".to_string());

        let mut token_payload = HashMap::new();
        token_payload.insert("token".to_string(), "tok-abc".to_string());

        let mut encrypted_map = HashMap::new();
        encrypted_map.insert(
            "api_key".to_string(),
            encrypt_auth(&api_key_payload, secret),
        );
        encrypted_map.insert("token".to_string(), encrypt_auth(&token_payload, secret));

        let result = decrypt_map_values(&encrypted_map, secret).unwrap();
        assert_eq!(result.get("api_key").unwrap(), "k-12345");
        assert_eq!(result.get("token").unwrap(), "tok-abc");
    }

    #[test]
    fn decrypt_map_values_skips_missing_key() {
        let secret = "skip-secret"; // pragma: allowlist secret

        // Payload does NOT contain the map key "missing_param".
        let mut payload = HashMap::new();
        payload.insert("other".to_string(), "value".to_string());

        let mut encrypted_map = HashMap::new();
        encrypted_map.insert("missing_param".to_string(), encrypt_auth(&payload, secret));

        let result = decrypt_map_values(&encrypted_map, secret).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn apply_invoke_auth_rejects_ftp_scheme() {
        let mut headers = HashMap::new();
        let result = apply_invoke_auth(
            "ftp://example.com/file",
            &HashMap::new(),
            &mut headers,
            None,
        );
        assert!(
            matches!(result, Err(AuthError::InvalidScheme(ref s)) if s == "ftp"),
            "expected InvalidScheme(ftp), got {result:?}"
        );
    }

    #[test]
    fn apply_invoke_auth_accepts_http() {
        let mut headers = HashMap::new();
        let result = apply_invoke_auth(
            "http://localhost:8080/path",
            &HashMap::new(),
            &mut headers,
            None,
        );
        assert!(result.is_ok());
    }

    #[test]
    fn apply_invoke_auth_accepts_https() {
        let mut headers = HashMap::new();
        let result = apply_invoke_auth(
            "https://secure.example.com/api",
            &HashMap::new(),
            &mut headers,
            None,
        );
        assert!(result.is_ok());
    }
}
