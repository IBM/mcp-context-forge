//! Auth application for A2A outbound requests.
//!
//! When an auth secret is configured at queue init, this module decrypts encrypted auth blobs
//! (matching Python services_auth: AES-GCM, SHA256 key, 12-byte nonce, base64url) and applies them.
//! Rust is the only decryption path; Python passes encrypted blobs only when secret is set (no Python fallback).

use std::collections::HashMap;

use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm,
};
use base64::Engine;
use log::warn;
use sha2::{Digest, Sha256};
use url::form_urlencoded;
use url::Url;

use crate::errors::A2AError;

/// Decrypt a base64url-encoded AES-GCM ciphertext (nonce || ciphertext) into a string->string map.
/// Matches Python `decode_auth`: key = SHA256(secret), 12-byte nonce, no AAD.
/// Returns empty map on empty or invalid input; errors on decrypt failure.
pub fn decrypt_auth(encoded_value: &str, secret: &str) -> Result<HashMap<String, String>, A2AError> {
    if encoded_value.is_empty() {
        return Ok(HashMap::new());
    }
    let padded = pad_base64url(encoded_value);
    let combined = base64::engine::general_purpose::URL_SAFE
        .decode(padded.as_bytes())
        .map_err(|e| A2AError::Auth(format!("base64 decode failed: {}", e)))?;
    if combined.len() < 12 {
        return Err(A2AError::Auth("ciphertext too short (missing nonce)".to_string()));
    }
    let (nonce_slice, ciphertext) = combined.split_at(12);
    let key = Sha256::digest(secret.as_bytes());
    let cipher = Aes256Gcm::new_from_slice(key.as_slice())
        .map_err(|e| A2AError::Auth(format!("AES-GCM key init failed: {}", e)))?;
    let plaintext = cipher
        .decrypt(nonce_slice.into(), ciphertext)
        .map_err(|e| A2AError::Auth(format!("decrypt failed: {}", e)))?;
    let s = String::from_utf8(plaintext).map_err(|e| A2AError::Auth(format!("plaintext not UTF-8: {}", e)))?;
    let value: HashMap<String, serde_json::Value> =
        serde_json::from_str(&s).map_err(|e| A2AError::Auth(format!("JSON parse failed: {}", e)))?;
    let out: HashMap<String, String> = value
        .into_iter()
        .filter_map(|(k, v)| {
            let str_val = match v {
                serde_json::Value::String(s) => s,
                other => other.to_string(),
            };
            Some((k, str_val))
        })
        .collect();
    Ok(out)
}

fn pad_base64url(s: &str) -> String {
    let rem = s.len() % 4;
    if rem == 0 {
        s.to_string()
    } else {
        format!("{}{}", s, "=".repeat(4 - rem))
    }
}

/// Decrypt each value in a map (keys unchanged); used for encrypted query params.
pub fn decrypt_map_values(
    enc_map: &HashMap<String, String>,
    secret: &str,
) -> Result<HashMap<String, String>, A2AError> {
    let mut out = HashMap::new();
    for (_k, v) in enc_map {
        let dec = decrypt_auth(v, secret)?;
        for (dk, dv) in dec {
            out.insert(dk, dv);
        }
    }
    Ok(out)
}

/// Outbound auth config for agent-to-agent calls (Bearer, ApiKey, OAuth).
/// For config/DB schema and documentation only; at invoke time only [`InvokeAuth`] is used (Rust builds it from decrypted or from encrypted blobs).
pub enum AuthConfig {
    Bearer(String),
    ApiKey {
        header: String,
        value: String,
    },
    OAuth {
        token_url: String,
        client_id: String,
        client_secret: String,
    },
}

/// Decrypted auth to apply to a single invoke request: query params and headers.
/// Built in Rust from decrypted auth (Rust decrypts when secret set) or from plain maps when no secret. All auth application in Rust; no Python fallback.
#[derive(Debug, Clone, Default)]
pub struct InvokeAuth {
    /// Query parameters to append/merge into the request URL (e.g. api_key, token).
    pub query_params: Option<HashMap<String, String>>,
    /// Headers to add to the request (e.g. Authorization, X-API-Key).
    pub headers: HashMap<String, String>,
}

/// Applies auth to a base URL and returns the final URL and headers for the HTTP request.
/// Merges auth query params with any existing query string on base_url (auth params override).
/// Fails if the URL is invalid or scheme is not http/https. Used by the invoke path only; no DB or Python fallback.
pub fn apply_invoke_auth(
    base_url: &str,
    auth: &InvokeAuth,
) -> Result<(String, HashMap<String, String>), A2AError> {
    let mut url = Url::parse(base_url).map_err(|e| {
        let msg = format!("Invalid invoke URL: {}", e);
        warn!("{}", msg);
        A2AError::Other(msg)
    })?;
    match url.scheme() {
        "http" | "https" => {}
        _ => {
            let msg = format!("Invoke URL scheme not allowed: {} (only http/https)", url.scheme());
            warn!("{}", msg);
            return Err(A2AError::Other(msg));
        }
    }

    if let Some(ref params) = auth.query_params {
        if !params.is_empty() {
            let mut pairs: Vec<(String, String)> = url
                .query_pairs()
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect();
            for (k, v) in params {
                pairs.retain(|(pk, _)| pk != k);
                pairs.push((k.clone(), v.clone()));
            }
            let mut ser = form_urlencoded::Serializer::new(String::new());
            for (k, v) in &pairs {
                ser.append_pair(k, v);
            }
            let new_query = ser.finish();
            url.set_query(if new_query.is_empty() { None } else { Some(&new_query) });
        }
    }

    Ok((url.to_string(), auth.headers.clone()))
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn test_auth_config_bearer() {
        let _ = AuthConfig::Bearer("token123".to_string());
    }

    #[test]
    fn test_auth_config_api_key() {
        let _ = AuthConfig::ApiKey {
            header: "X-API-Key".to_string(),
            value: "secret".to_string(),
        };
    }

    #[test]
    fn test_auth_config_oauth() {
        let _ = AuthConfig::OAuth {
            token_url: "https://auth.example.com/token".to_string(),
            client_id: "client".to_string(),
            client_secret: "secret".to_string(),
        };
    }

    #[test]
    fn test_apply_invoke_auth_url_only() {
        let auth = InvokeAuth::default();
        let (url, headers) = apply_invoke_auth("https://api.example.com/mcp", &auth).unwrap();
        assert_eq!(url, "https://api.example.com/mcp");
        assert!(headers.is_empty());
    }

    #[test]
    fn test_apply_invoke_auth_query_params() {
        let mut params = HashMap::new();
        params.insert("api_key".to_string(), "secret123".to_string());
        let auth = InvokeAuth {
            query_params: Some(params),
            headers: HashMap::new(),
        };
        let (url, _) = apply_invoke_auth("https://api.example.com/mcp", &auth).unwrap();
        assert!(url.contains("api_key="));
        assert!(url.contains("secret123"));
    }

    #[test]
    fn test_apply_invoke_auth_headers() {
        let mut headers = HashMap::new();
        headers.insert("Authorization".to_string(), "Bearer tok".to_string());
        let auth = InvokeAuth {
            query_params: None,
            headers,
        };
        let (url, h) = apply_invoke_auth("https://api.example.com/mcp", &auth).unwrap();
        assert_eq!(url, "https://api.example.com/mcp");
        assert_eq!(h.get("Authorization").map(String::as_str), Some("Bearer tok"));
    }

    #[test]
    fn test_apply_invoke_auth_merge_existing_query() {
        let mut params = HashMap::new();
        params.insert("api_key".to_string(), "key123".to_string());
        let auth = InvokeAuth {
            query_params: Some(params),
            headers: HashMap::new(),
        };
        let (url, _) = apply_invoke_auth("https://api.example.com/mcp?q=test", &auth).unwrap();
        assert!(url.contains("q=test"));
        assert!(url.contains("api_key=key123"));
    }

    #[test]
    fn test_apply_invoke_auth_invalid_url_returns_err() {
        let auth = InvokeAuth::default();
        let err = apply_invoke_auth("not-a-valid-url", &auth).unwrap_err();
        assert!(err.to_string().to_lowercase().contains("invalid"));
    }

    #[test]
    fn test_apply_invoke_auth_file_scheme_rejected() {
        let auth = InvokeAuth::default();
        let err = apply_invoke_auth("file:///etc/passwd", &auth).unwrap_err();
        assert!(err.to_string().to_lowercase().contains("not allowed"));
    }

    #[test]
    fn test_decrypt_auth_empty_returns_empty_map() {
        let m = decrypt_auth("", "secret").unwrap();
        assert!(m.is_empty());
    }

    #[test]
    fn test_decrypt_auth_invalid_base64_returns_err() {
        let err = decrypt_auth("not-valid-base64!!!", "secret").unwrap_err();
        assert!(matches!(err, A2AError::Auth(_)));
    }
}
