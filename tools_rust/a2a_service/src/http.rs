// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! HTTP JSON DTOs and conversion for A2A invoke (single and batch).
//! Compatible with the Python A2A invoke contract (unified response shape).

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;

use crate::auth::{apply_invoke_auth, decrypt_auth, decrypt_map_values, InvokeAuth};
use crate::errors::A2AError;
use crate::invoker::{A2AInvokeRequest, A2AInvokeResult};

/// Single request in the batch invoke JSON body.
/// Matches the Python tuple shape: id, base_url, auth, body, optional metadata.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InvokeRequestDto {
    pub id: u32,
    pub base_url: String,
    #[serde(default)]
    pub auth_query_params: Option<HashMap<String, String>>,
    #[serde(default)]
    pub auth_headers: Option<HashMap<String, String>>,
    /// Request body (UTF-8). Sent as-is to the agent endpoint.
    pub body: String,
    #[serde(default)]
    pub correlation_id: Option<String>,
    #[serde(default)]
    pub traceparent: Option<String>,
    #[serde(default)]
    pub agent_name: Option<String>,
    #[serde(default)]
    pub agent_id: Option<String>,
    #[serde(default)]
    pub interaction_type: Option<String>,
    #[serde(default)]
    pub scope_id: Option<String>,
    #[serde(default)]
    pub request_id: Option<String>,
    /// When auth_secret is set, decrypt and use instead of auth_headers.
    #[serde(default)]
    pub auth_headers_encrypted: Option<String>,
    /// When auth_secret is set, decrypt and use instead of auth_query_params.
    #[serde(default)]
    pub auth_query_params_encrypted: Option<HashMap<String, String>>,
}

/// Single invoke result for JSON response (unified shape with Python).
#[derive(Debug, Clone, Serialize)]
pub struct InvokeResultDto {
    pub id: u32,
    pub status_code: u16,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parsed: Option<JsonValue>,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub agent_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<JsonValue>,
    pub duration_secs: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metric_row: Option<MetricRowDto>,
}

#[derive(Debug, Clone, Serialize)]
pub struct MetricRowDto {
    pub agent_id: String,
    pub timestamp_secs: f64,
    pub response_time: f64,
    pub is_success: bool,
    pub interaction_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
}

/// Parse JSON request DTOs into `A2AInvokeRequest` list (with optional auth decryption).
pub fn parse_requests_from_json(
    requests: &[InvokeRequestDto],
    auth_secret: Option<&str>,
) -> Result<Vec<A2AInvokeRequest>, A2AError> {
    let mut out = Vec::with_capacity(requests.len());
    for (i, dto) in requests.iter().enumerate() {
        let auth_query_params = if let Some(ref enc) = dto.auth_query_params_encrypted {
            let secret = auth_secret.ok_or_else(|| {
                A2AError::Auth("auth_query_params_encrypted set but no auth_secret".to_string())
            })?;
            Some(decrypt_map_values(enc, secret)?)
        } else {
            dto.auth_query_params.clone()
        };
        let mut auth_headers: HashMap<String, String> = dto.auth_headers.clone().unwrap_or_default();
        if let Some(ref enc) = dto.auth_headers_encrypted {
            let secret = auth_secret.ok_or_else(|| {
                A2AError::Auth("auth_headers_encrypted set but no auth_secret".to_string())
            })?;
            let dec = decrypt_auth(enc, secret)?;
            auth_headers.extend(dec);
        }
        auth_headers
            .entry("Content-Type".to_string())
            .or_insert_with(|| "application/json".to_string());
        if let Some(ref c) = dto.correlation_id {
            auth_headers.insert("X-Correlation-ID".to_string(), c.clone());
        }
        if let Some(ref t) = dto.traceparent {
            auth_headers.insert("traceparent".to_string(), t.clone());
        }
        let auth = InvokeAuth {
            query_params: auth_query_params,
            headers: auth_headers,
        };
        let (url, headers) = apply_invoke_auth(&dto.base_url, &auth)?;
        out.push(A2AInvokeRequest {
            id: dto.id as usize,
            url,
            body: dto.body.as_bytes().to_vec(),
            headers,
            correlation_id: dto.correlation_id.clone(),
            traceparent: dto.traceparent.clone(),
            agent_name: dto.agent_name.clone(),
            agent_id: dto.agent_id.clone(),
            interaction_type: dto.interaction_type.clone(),
            scope_id: dto.scope_id.clone(),
            request_id: dto.request_id.clone(),
        });
        let _ = i;
    }
    Ok(out)
}

fn success_and_error_message(r: &A2AInvokeResult) -> (bool, Option<String>) {
    match r.result.as_ref() {
        Ok(resp) => (
            crate::errors::is_success_http_status(resp.status_code),
            if crate::errors::is_success_http_status(resp.status_code) {
                None
            } else if resp.body.is_empty() {
                Some("Internal Server Error".to_string())
            } else {
                Some(resp.body.clone())
            },
        ),
        Err(e) => (false, Some(e.to_string())),
    }
}

/// Convert invoker results to JSON DTOs (unified shape with Python).
pub fn results_to_json(
    results: Vec<A2AInvokeResult>,
    end_time_secs: f64,
) -> Vec<InvokeResultDto> {
    results
        .into_iter()
        .map(|r| {
            let (success, error_message) = success_and_error_message(&r);
            let metric_row = match (r.agent_id.as_ref(), r.interaction_type.as_ref()) {
                (Some(aid), Some(it)) => Some(MetricRowDto {
                    agent_id: aid.clone(),
                    timestamp_secs: end_time_secs,
                    response_time: r.duration_secs,
                    is_success: success,
                    interaction_type: it.clone(),
                    error_message: error_message.clone(),
                }),
                _ => None,
            };
            let (status_code, body, parsed, error, code, agent_name, details) = match r.result.as_ref() {
                Ok(resp) => (
                    resp.status_code,
                    Some(resp.body.clone()),
                    resp.parsed.clone(),
                    None,
                    None,
                    None,
                    None,
                ),
                Err(e) => (
                    e.http_status(),
                    None,
                    None,
                    Some(e.to_string()),
                    Some(e.error_code().to_string()),
                    r.agent_name.clone(),
                    None,
                ),
            };
            InvokeResultDto {
                id: r.id as u32,
                status_code,
                body,
                parsed,
                success,
                error,
                code,
                agent_name,
                details,
                duration_secs: r.duration_secs,
                metric_row,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::errors::A2AError;
    use crate::invoker::A2AResponse;
    use std::sync::Arc;

    use super::*;

    #[test]
    fn test_parse_requests_from_json_minimal() {
        let dto = InvokeRequestDto {
            id: 1,
            base_url: "https://example.com/mcp".to_string(),
            auth_query_params: None,
            auth_headers: None,
            body: r#"{"jsonrpc":"2.0"}"#.to_string(),
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
            auth_headers_encrypted: None,
            auth_query_params_encrypted: None,
        };
        let reqs = parse_requests_from_json(&[dto], None).unwrap();
        assert_eq!(reqs.len(), 1);
        assert_eq!(reqs[0].id, 1);
        assert_eq!(reqs[0].url, "https://example.com/mcp");
        assert!(reqs[0].headers.contains_key("Content-Type"));
    }

    #[test]
    fn test_parse_requests_encrypted_without_secret_returns_err() {
        let mut enc = HashMap::new();
        enc.insert("k".to_string(), "v".to_string());
        let dto = InvokeRequestDto {
            id: 1,
            base_url: "https://example.com".to_string(),
            auth_query_params: None,
            auth_headers: None,
            body: "{}".to_string(),
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
            auth_headers_encrypted: Some("x".to_string()),
            auth_query_params_encrypted: None,
        };
        let err = parse_requests_from_json(&[dto], None).unwrap_err();
        assert!(matches!(err, A2AError::Auth(_)));
    }

    #[test]
    fn test_parse_requests_invalid_url_returns_err() {
        let dto = InvokeRequestDto {
            id: 1,
            base_url: "not-a-url".to_string(),
            auth_query_params: None,
            auth_headers: None,
            body: "{}".to_string(),
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
            auth_headers_encrypted: None,
            auth_query_params_encrypted: None,
        };
        let err = parse_requests_from_json(&[dto], None).unwrap_err();
        assert!(matches!(err, A2AError::Other(_)));
    }

    #[test]
    fn test_results_to_json_success() {
        let results = vec![crate::invoker::A2AInvokeResult {
            id: 0,
            result: Arc::new(Ok(A2AResponse {
                status_code: 200,
                body: r#"{"ok":true}"#.to_string(),
                parsed: Some(serde_json::json!({"ok": true})),
            })),
            duration_secs: 0.5,
            agent_key: "agent1".to_string(),
            agent_name: Some("agent1".to_string()),
            agent_id: Some("id1".to_string()),
            interaction_type: Some("query".to_string()),
        }];
        let dtos = results_to_json(results, 1000.0);
        assert_eq!(dtos.len(), 1);
        assert_eq!(dtos[0].id, 0);
        assert_eq!(dtos[0].status_code, 200);
        assert!(dtos[0].success);
        assert!(dtos[0].metric_row.is_some());
    }

    #[test]
    fn test_results_to_json_error() {
        let results = vec![crate::invoker::A2AInvokeResult {
            id: 1,
            result: Arc::new(Err(A2AError::Timeout(std::time::Duration::from_secs(5)))),
            duration_secs: 0.0,
            agent_key: "agent1".to_string(),
            agent_name: Some("a".to_string()),
            agent_id: None,
            interaction_type: None,
        }];
        let dtos = results_to_json(results, 1000.0);
        assert_eq!(dtos.len(), 1);
        assert!(!dtos[0].success);
        assert_eq!(dtos[0].code.as_deref(), Some("timeout"));
        assert_eq!(dtos[0].status_code, 504);
    }
}
