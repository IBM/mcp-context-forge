//! Strict MCP request classifier used before authorization.

use async_trait::async_trait;
use bytes::Bytes;
use praxis_filter::{
    BodyAccess, BodyMode, FilterAction, FilterError, HttpFilter, HttpFilterContext, Rejection,
};
use serde::Deserialize;
use serde_json::Value;

const DEFAULT_MAX_BODY_BYTES: usize = 1_048_576;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ClassifierConfig {
    #[serde(default = "default_max_body_bytes")]
    max_body_bytes: usize,
}

const fn default_max_body_bytes() -> usize {
    DEFAULT_MAX_BODY_BYTES
}

#[derive(Debug, Clone, Eq, PartialEq)]
enum McpEntity {
    Tool(String),
    Resource(String),
    Prompt(String),
}

impl McpEntity {
    fn name(&self) -> &str {
        match self {
            Self::Tool(name) | Self::Resource(name) | Self::Prompt(name) => name,
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
struct ClassifiedRequest {
    method: String,
    entity: Option<McpEntity>,
    jsonrpc_id: Option<String>,
}

#[derive(Debug, thiserror::Error)]
enum ClassifierError {
    #[error("invalid MCP request")]
    Invalid,
    #[error("unsupported MCP method")]
    Unsupported,
}

fn required_string(value: &Value, key: &str) -> Result<String, ClassifierError> {
    value
        .get("params")
        .and_then(|params| params.get(key))
        .and_then(Value::as_str)
        .filter(|item| !item.is_empty())
        .map(str::to_owned)
        .ok_or(ClassifierError::Invalid)
}

fn parse_mcp_request(body: &[u8]) -> Result<ClassifiedRequest, ClassifierError> {
    let value: Value = serde_json::from_slice(body).map_err(|_| ClassifierError::Invalid)?;
    let object = value.as_object().ok_or(ClassifierError::Invalid)?;
    if object.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err(ClassifierError::Invalid);
    }
    let method = object
        .get("method")
        .and_then(Value::as_str)
        .filter(|item| !item.is_empty())
        .ok_or(ClassifierError::Invalid)?;
    let entity = match method {
        "tools/call" => Some(McpEntity::Tool(required_string(&value, "name")?)),
        "resources/read" => Some(McpEntity::Resource(required_string(&value, "uri")?)),
        "prompts/get" => Some(McpEntity::Prompt(required_string(&value, "name")?)),
        "completion/complete"
        | "initialize"
        | "logging/setLevel"
        | "notifications/initialized"
        | "notifications/prompts/list_changed"
        | "notifications/resources/list_changed"
        | "notifications/tools/list_changed"
        | "ping"
        | "prompts/list"
        | "resources/list"
        | "tools/list" => None,
        _ => return Err(ClassifierError::Unsupported),
    };
    let jsonrpc_id = object.get("id").map(Value::to_string);
    Ok(ClassifiedRequest {
        method: method.to_owned(),
        entity,
        jsonrpc_id,
    })
}

fn reject_invalid() -> FilterAction {
    FilterAction::Reject(
        Rejection::status(400)
            .with_header("content-type", "application/json")
            .with_body(r#"{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"invalid request"}}"#),
    )
}

/// Locally linked fail-closed MCP classifier.
pub struct McpClassifierFilter {
    max_body_bytes: usize,
}

impl McpClassifierFilter {
    /// Construct the classifier from a flat Praxis filter configuration.
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let parsed: ClassifierConfig = serde_yaml::from_value(config.clone())?;
        if parsed.max_body_bytes == 0 {
            return Err("mcp: max_body_bytes must be greater than zero".into());
        }
        Ok(Box::new(Self {
            max_body_bytes: parsed.max_body_bytes,
        }))
    }
}

#[async_trait]
impl HttpFilter for McpClassifierFilter {
    fn name(&self) -> &'static str {
        "mcp"
    }

    fn request_body_access(&self) -> BodyAccess {
        BodyAccess::ReadOnly
    }

    fn request_body_mode(&self) -> BodyMode {
        BodyMode::StreamBuffer {
            max_bytes: Some(self.max_body_bytes),
        }
    }

    async fn on_request(
        &self,
        ctx: &mut HttpFilterContext<'_>,
    ) -> Result<FilterAction, FilterError> {
        if ctx.request.method != http::Method::POST {
            return Ok(reject_invalid());
        }
        Ok(FilterAction::Continue)
    }

    async fn on_request_body(
        &self,
        ctx: &mut HttpFilterContext<'_>,
        body: &mut Option<Bytes>,
        end_of_stream: bool,
    ) -> Result<FilterAction, FilterError> {
        if !end_of_stream {
            return Ok(FilterAction::Continue);
        }
        let Some(bytes) = body.as_ref() else {
            return Ok(reject_invalid());
        };
        let classified = match parse_mcp_request(bytes) {
            Ok(request) => request,
            Err(ClassifierError::Invalid | ClassifierError::Unsupported) => {
                return Ok(reject_invalid());
            }
        };
        ctx.set_metadata("mcp.method", classified.method);
        if let Some(entity) = classified.entity {
            ctx.set_metadata("mcp.name", entity.name());
        }
        if let Some(jsonrpc_id) = classified.jsonrpc_id.filter(|value| value.len() <= 256) {
            ctx.set_metadata("mcp.jsonrpc_id", jsonrpc_id);
        }
        Ok(FilterAction::Release)
    }
}

#[cfg(test)]
mod tests {
    use super::{McpEntity, parse_mcp_request};

    #[test]
    fn parses_supported_entity_request() {
        let parsed = parse_mcp_request(
            br#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search"}}"#,
        )
        .expect("supported request");

        assert_eq!(parsed.method, "tools/call");
        assert_eq!(parsed.entity, Some(McpEntity::Tool("search".to_owned())));
    }

    #[test]
    fn rejects_malformed_json() {
        assert!(parse_mcp_request(br#"{"jsonrpc":"2.0""#).is_err());
    }

    #[test]
    fn rejects_batches_and_unknown_methods() {
        assert!(parse_mcp_request(br#"[]"#).is_err());
        assert!(
            parse_mcp_request(br#"{"jsonrpc":"2.0","id":1,"method":"a2a/send","params":{}}"#)
                .is_err()
        );
    }

    #[test]
    fn rejects_missing_or_non_string_entity_selector() {
        assert!(
            parse_mcp_request(br#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}"#)
                .is_err()
        );
        assert!(
            parse_mcp_request(
                br#"{"jsonrpc":"2.0","id":1,"method":"resources/read","params":{"uri":7}}"#,
            )
            .is_err()
        );
    }
}
