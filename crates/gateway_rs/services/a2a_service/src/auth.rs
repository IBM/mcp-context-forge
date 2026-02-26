use std::collections::HashMap;

use tracing::warn;
use url::form_urlencoded;
use url::Url;

use crate::errors::A2AError;

/// Outbound auth config for agent-to-agent calls (Bearer, ApiKey, OAuth).
/// Used when configuring an agent; actual apply is via InvokeAuth at invoke time.
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

/// Decrypted auth to apply to a single invoke request. All auth application happens in Rust;
/// Python only does DB and decryption, then passes this struct. No Python fallback during invoke.
#[derive(Debug, Clone, Default)]
pub struct InvokeAuth {
    /// Query parameters to append/merge into the request URL (e.g. api_key, token).
    pub query_params: Option<HashMap<String, String>>,
    /// Headers to add to the request (e.g. Authorization, X-API-Key).
    pub headers: HashMap<String, String>,
}

/// Applies auth to a base URL and returns the final URL and headers for the HTTP request.
/// Merges auth query params with any existing query string on base_url (auth params override).
/// Used by the invoke path only; no DB or Python fallback.
pub fn apply_invoke_auth(
    base_url: &str,
    auth: &InvokeAuth,
) -> Result<(String, HashMap<String, String>), A2AError> {
    let mut url = Url::parse(base_url).map_err(|e| {
        let msg = format!("Invalid invoke URL: {}", e);
        warn!("{}", msg);
        A2AError::Other(msg)
    })?;

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
}
