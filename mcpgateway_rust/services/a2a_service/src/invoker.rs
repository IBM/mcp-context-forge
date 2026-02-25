use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use futures::future::{join_all, FutureExt};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest::Client;
use serde_json::Value as JsonValue;

use crate::errors::A2AError;
use crate::metrics::MetricsCollector;

/// A2A invoke response with HTTP status, raw body, and optional parsed JSON.
/// When the body is valid JSON, `parsed` is set so Python can skip json.loads.
#[derive(Debug)]
pub struct A2AResponse {
    pub status_code: u16,
    pub body: String,
    /// Parsed JSON when body is valid JSON; None for invalid or non-JSON body.
    pub parsed: Option<JsonValue>,
}

/// Extension trait to convert Python headers dict to HeaderMap.
/// Skips invalid header names/values.
trait IntoHeaderMap {
    fn into_header_map(&self) -> HeaderMap;
}

impl IntoHeaderMap for HashMap<String, String> {
    fn into_header_map(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        for (k, v) in self {
            if let (Ok(name), Ok(value)) = (
                HeaderName::try_from(k.as_str()),
                HeaderValue::try_from(v.as_str()),
            ) {
                headers.insert(name, value);
            }
        }
        headers
    }
}

/// Core HTTP invoker for outbound A2A calls.
///
/// Entry point for Python: pass pre-built url (with query auth if any),
/// JSON body bytes, and headers dict. No auth logic in Rust—Python handles
/// decode_auth, apply_query_param_auth, etc.
pub struct A2AInvoker {
    client: Client,
    metrics: Arc<MetricsCollector>,
}

impl A2AInvoker {
    pub fn new(client: Client, metrics: Arc<MetricsCollector>) -> Self {
        Self { client, metrics }
    }

    /// Invoke a single A2A agent. Body is raw JSON bytes (no parse in Rust).
    pub async fn invoke(
        &self,
        agent_url: &str,
        body: &[u8],
        headers: &HashMap<String, String>,
        timeout: Duration,
    ) -> Result<A2AResponse, A2AError> {
        let header_map = headers.into_header_map();

        let response = self
            .client
            .post(agent_url)
            .body(body.to_vec())
            .headers(header_map)
            .timeout(timeout)
            .send()
            .await?;

        let status_code = response.status().as_u16();
        let body = response.text().await?;
        let parsed = serde_json::from_str(&body).ok();
        Ok(A2AResponse {
            status_code,
            body,
            parsed,
        })
    }

    /// Invoke multiple A2A agents concurrently. Each item: (url, body, headers).
    /// Results preserve input order.
    pub async fn invoke_batch(
        &self,
        requests: Vec<(String, Vec<u8>, HashMap<String, String>)>,
        timeout: Duration,
    ) -> Vec<Result<A2AResponse, A2AError>> {
        let futures = requests
            .into_iter()
            .map(|(url, body, headers)| {
                async move { self.invoke(&url, &body, &headers, timeout).await }.boxed()
            })
            .collect::<Vec<_>>();
        join_all(futures).await
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use reqwest::Client;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    use super::A2AInvoker;
    use crate::errors::A2AError;
    use crate::metrics::MetricsCollector;

    fn test_invoker() -> A2AInvoker {
        let client = Client::builder().build().expect("reqwest client");
        let metrics = Arc::new(MetricsCollector::new());
        A2AInvoker::new(client, metrics)
    }

    #[tokio::test]
    async fn test_invoke_success_returns_raw_body() {
        let mock_server = MockServer::start().await;
        let body_json = r#"{"jsonrpc":"2.0","result":{"test":true}}"#;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_raw(body_json.as_bytes(), "application/json"),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let result = inv
            .invoke(
                &mock_server.uri(),
                body_json.as_bytes(),
                &headers,
                Duration::from_secs(5),
            )
            .await
            .unwrap();

        assert_eq!(result.status_code, 200);
        assert_eq!(result.body, body_json);
    }

    #[tokio::test]
    async fn test_invoke_non_2xx_returns_ok_with_status_and_body() {
        let mock_server = MockServer::start().await;
        let body_text = r#"{"error":"not found"}"#;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(404).set_body_raw(body_text.as_bytes(), "application/json"),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let result = inv
            .invoke(
                &mock_server.uri(),
                b"{}",
                &headers,
                Duration::from_secs(5),
            )
            .await
            .unwrap();

        assert_eq!(result.status_code, 404);
        assert_eq!(result.body, body_text);
    }

    #[tokio::test]
    async fn test_invoke_non_json_body_returned_as_raw_string() {
        let mock_server = MockServer::start().await;
        let body_text = "<html><body>Error 500</body></html>";
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(500).set_body_string(body_text),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let headers = HashMap::new();
        let result = inv
            .invoke(
                &mock_server.uri(),
                b"{}",
                &headers,
                Duration::from_secs(5),
            )
            .await
            .unwrap();

        assert_eq!(result.status_code, 500);
        assert_eq!(result.body, body_text);
    }

    #[tokio::test]
    async fn test_invoke_headers_passed_through() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(ResponseTemplate::new(200).set_body_string("{}"))
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let mut headers = HashMap::new();
        headers.insert("Content-Type".to_string(), "application/json".to_string());
        headers.insert("X-Custom".to_string(), "custom-value".to_string());

        let result = inv
            .invoke(
                &mock_server.uri(),
                b"{}",
                &headers,
                Duration::from_secs(5),
            )
            .await
            .unwrap();

        assert_eq!(result.status_code, 200);
    }

    #[tokio::test]
    async fn test_invoke_invalid_url_returns_err() {
        let inv = test_invoker();
        let headers = HashMap::new();
        let result = inv
            .invoke(
                "http://invalid-domain-that-does-not-exist-12345.local/",
                b"{}",
                &headers,
                Duration::from_secs(1),
            )
            .await;

        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), A2AError::Http(_)));
    }

    #[tokio::test]
    async fn test_invoke_batch_preserves_order() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_string(r#"{"id":1}"#),
            )
            .mount(&mock_server)
            .await;

        let inv = test_invoker();
        let requests = vec![
            (
                mock_server.uri().to_string(),
                b"{}".to_vec(),
                HashMap::new(),
            ),
            (
                mock_server.uri().to_string(),
                b"{}".to_vec(),
                HashMap::new(),
            ),
        ];

        let results = inv
            .invoke_batch(requests, Duration::from_secs(5))
            .await;

        assert_eq!(results.len(), 2);
        for r in &results {
            let resp = r.as_ref().unwrap();
            assert_eq!(resp.status_code, 200);
        }
    }
}
