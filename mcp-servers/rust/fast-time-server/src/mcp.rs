// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::body;
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use chrono::Utc;
use serde_json::json;
use std::sync::atomic::{AtomicU64, Ordering};

use crate::config::{APP_NAME, APP_VERSION, MCP_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS};
use crate::delay::{compute_delay, validate_delay};
use crate::time::{parse_time_in_timezone, parse_timezone};

static DIRECT_REQUEST_COUNT: AtomicU64 = AtomicU64::new(0);

pub(crate) fn json_response(body: String) -> Response {
    ([(header::CONTENT_TYPE, "application/json")], body).into_response()
}

pub(crate) fn id_json(id: Option<&serde_json::Value>) -> String {
    id.and_then(|value| serde_json::to_string(value).ok())
        .unwrap_or_else(|| "null".to_string())
}

pub(crate) fn initialize_body(id: Option<&serde_json::Value>, protocol_version: &str) -> String {
    format!(
        r#"{{"jsonrpc":"2.0","id":{},"result":{{"protocolVersion":"{}","capabilities":{{"tools":{{}}}},"serverInfo":{{"name":"{}","version":"{}"}},"instructions":"Ultra-fast MCP test server."}}}}"#,
        id_json(id),
        protocol_version,
        APP_NAME,
        APP_VERSION
    )
}

/// Echo back the client's requested protocol version when supported, otherwise
/// advertise the latest version this server speaks.
pub(crate) fn negotiate_protocol_version(req: &serde_json::Value) -> &'static str {
    let requested = req
        .get("params")
        .and_then(|params| params.get("protocolVersion"))
        .and_then(serde_json::Value::as_str);
    SUPPORTED_PROTOCOL_VERSIONS
        .iter()
        .copied()
        .find(|&supported| Some(supported) == requested)
        .unwrap_or(MCP_PROTOCOL_VERSION)
}

pub(crate) fn tools_list_response(id: Option<&serde_json::Value>) -> Response {
    json_response(format!(
        r#"{{"jsonrpc":"2.0","id":{},"result":{{"tools":[{{"name":"echo","description":"Echo back the provided message.","inputSchema":{{"type":"object","properties":{{"message":{{"type":"string"}},"delay":{{"type":"integer","minimum":0,"maximum":60000}},"delay_stddev":{{"type":"number","minimum":0}}}},"required":["message"]}}}},{{"name":"get_system_time","description":"Get current system time in the specified IANA timezone.","inputSchema":{{"type":"object","properties":{{"timezone":{{"type":"string"}}}}}}}},{{"name":"convert_time","description":"Convert a time value from a source IANA timezone to a target IANA timezone.","inputSchema":{{"type":"object","properties":{{"time":{{"type":"string"}},"source_timezone":{{"type":"string"}},"target_timezone":{{"type":"string"}}}},"required":["time","source_timezone","target_timezone"]}}}},{{"name":"schema_error","description":"Always returns isError=true.","inputSchema":{{"type":"object","properties":{{}}}},"outputSchema":{{"type":"object","properties":{{"recognitionId":{{"type":"string"}},"message":{{"type":"string"}}}},"required":["recognitionId"]}}}},{{"name":"schema_success","description":"Returns a JSON payload that conforms to the declared outputSchema.","inputSchema":{{"type":"object","properties":{{}}}},"outputSchema":{{"type":"object","properties":{{"recognitionId":{{"type":"string"}},"message":{{"type":"string"}}}},"required":["recognitionId"]}}}},{{"name":"get_stats","description":"Get server statistics including request count and uptime.","inputSchema":{{"type":"object","properties":{{}}}}}}]}}}}"#,
        id_json(id)
    ))
}

pub(crate) async fn tools_call_response(
    id: Option<&serde_json::Value>,
    req: &serde_json::Value,
) -> Response {
    let params = req.get("params").unwrap_or(&serde_json::Value::Null);
    let name = params
        .get("name")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let arguments = params.get("arguments").unwrap_or(&serde_json::Value::Null);

    match name {
        "echo" => {
            let Some(arguments) = arguments_object(arguments) else {
                return invalid_params_response(id, "arguments must be an object");
            };
            let Some(message) = required_string(arguments, "message") else {
                return invalid_params_response(id, "message must be a string");
            };
            let Some(delay) = optional_u64(arguments, "delay") else {
                return invalid_params_response(id, "delay must be an unsigned integer");
            };
            let Some(delay_stddev) = optional_f64(arguments, "delay_stddev") else {
                return invalid_params_response(id, "delay_stddev must be a number");
            };
            let Ok(delay) = validate_delay(delay) else {
                return invalid_params_response(id, "delay exceeds the 60000 ms limit");
            };

            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            if let Some(ms) = delay
                && ms > 0
            {
                let actual_ms = compute_delay(ms, delay_stddev);
                tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
            }
            text_result_response(id, message, false)
        }
        "get_system_time" => {
            let timezone = if arguments.is_null() {
                None
            } else {
                let Some(arguments) = arguments_object(arguments) else {
                    return invalid_params_response(id, "arguments must be an object");
                };
                let Some(timezone) = optional_string(arguments, "timezone") else {
                    return invalid_params_response(id, "timezone must be a string");
                };
                timezone
            };
            let timezone = timezone.unwrap_or("UTC");

            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            match parse_timezone(timezone) {
                Ok(timezone) => text_result_response(id, &timezone.format_utc(Utc::now()), false),
                Err(err) => {
                    text_result_response(id, &format!("Invalid timezone '{timezone}': {err}"), true)
                }
            }
        }
        "convert_time" => convert_time_response(id, arguments),
        "schema_error" => {
            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            text_result_response(id, "You cannot send more than 200 points", true)
        }
        "schema_success" => json_response({
            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            format!(
                r#"{{"jsonrpc":"2.0","id":{},"result":{{"content":[{{"type":"text","text":"{{\"recognitionId\":\"rec-123\",\"message\":\"ok\"}}"}}],"structuredContent":{{"recognitionId":"rec-123","message":"ok"}},"isError":false}}}}"#,
                id_json(id)
            )
        }),
        "get_stats" => {
            let count = DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed) + 1;
            text_result_response(
                id,
                &format!(
                    "{{\n  \"server\": \"{}\",\n  \"version\": \"{}\",\n  \"requests_handled\": {}\n}}",
                    APP_NAME, APP_VERSION, count
                ),
                false,
            )
        }
        _ => error_response(id, -32602, "Unknown tool", Some(json!({ "tool": name }))),
    }
}

pub(crate) fn empty_result_response(id: Option<&serde_json::Value>) -> Response {
    json_response(format!(
        r#"{{"jsonrpc":"2.0","id":{},"result":{{}}}}"#,
        id_json(id)
    ))
}

pub(crate) fn error_response(
    id: Option<&serde_json::Value>,
    code: i32,
    message: &str,
    data: Option<serde_json::Value>,
) -> Response {
    error_response_with_status(StatusCode::OK, id, code, message, data)
}

pub(crate) fn error_response_with_status(
    status: StatusCode,
    id: Option<&serde_json::Value>,
    code: i32,
    message: &str,
    data: Option<serde_json::Value>,
) -> Response {
    let escaped_message = serde_json::to_string(message).unwrap_or_else(|_| "\"\"".to_string());
    let data = data
        .map(|value| format!(r#","data":{}"#, value))
        .unwrap_or_default();
    let mut response = json_response(format!(
        r#"{{"jsonrpc":"2.0","id":{},"error":{{"code":{},"message":{}{}}}}}"#,
        id_json(id),
        code,
        escaped_message,
        data
    ));
    *response.status_mut() = status;
    response
}

pub(crate) async fn sse_message_response(req: &serde_json::Value) -> Option<String> {
    let id = Some(req.get("id")?);

    let method = req
        .get("method")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let response = match method {
        "initialize" => json_response(initialize_body(id, negotiate_protocol_version(req))),
        "ping" => empty_result_response(id),
        "tools/list" => tools_list_response(id),
        "tools/call" => tools_call_response(id, req).await,
        _ => error_response(id, -32601, "Method not found", None),
    };

    Some(response_body(response).await)
}

fn convert_time_response(
    id: Option<&serde_json::Value>,
    arguments: &serde_json::Value,
) -> Response {
    let Some(arguments) = arguments_object(arguments) else {
        return invalid_params_response(id, "arguments must be an object");
    };
    let Some(time) = required_string(arguments, "time") else {
        return invalid_params_response(id, "time must be a string");
    };
    let Some(source_timezone) = required_string(arguments, "source_timezone") else {
        return invalid_params_response(id, "source_timezone must be a string");
    };
    let Some(target_timezone) = required_string(arguments, "target_timezone") else {
        return invalid_params_response(id, "target_timezone must be a string");
    };

    DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);

    let source_timezone = match parse_timezone(source_timezone) {
        Ok(timezone) => timezone,
        Err(err) => {
            return text_result_response(id, &format!("invalid source timezone: {err}"), true);
        }
    };
    let target_timezone = match parse_timezone(target_timezone) {
        Ok(timezone) => timezone,
        Err(err) => {
            return text_result_response(id, &format!("invalid target timezone: {err}"), true);
        }
    };
    match parse_time_in_timezone(time, &source_timezone) {
        Ok(parsed) => {
            let converted = target_timezone.format_utc(parsed);
            text_result_response(id, &converted, false)
        }
        Err(_) => text_result_response(id, &format!("invalid time format: {time}"), true),
    }
}

fn arguments_object(
    value: &serde_json::Value,
) -> Option<&serde_json::Map<String, serde_json::Value>> {
    value.as_object()
}

fn required_string<'a>(
    arguments: &'a serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<&'a str> {
    arguments.get(field)?.as_str()
}

fn optional_string<'a>(
    arguments: &'a serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<&'a str>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_str().map(Some),
        None => Some(None),
    }
}

fn optional_u64(
    arguments: &serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<u64>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_u64().map(Some),
        None => Some(None),
    }
}

fn optional_f64(
    arguments: &serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<f64>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_f64().map(Some),
        None => Some(None),
    }
}

fn text_result_response(id: Option<&serde_json::Value>, text: &str, is_error: bool) -> Response {
    let escaped = serde_json::to_string(text).unwrap_or_else(|_| "\"\"".to_string());
    json_response(format!(
        r#"{{"jsonrpc":"2.0","id":{},"result":{{"content":[{{"type":"text","text":{}}}],"isError":{}}}}}"#,
        id_json(id),
        escaped,
        is_error
    ))
}

fn invalid_params_response(id: Option<&serde_json::Value>, message: &str) -> Response {
    error_response(id, -32602, message, None)
}

async fn response_body(response: Response) -> String {
    body::to_bytes(response.into_body(), usize::MAX)
        .await
        .ok()
        .and_then(|bytes| String::from_utf8(bytes.to_vec()).ok())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn response_text(response: Response) -> String {
        let bytes = body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("response body should be readable");
        String::from_utf8(bytes.to_vec()).expect("response body should be utf-8")
    }

    async fn response_json(response: Response) -> serde_json::Value {
        serde_json::from_str(&response_text(response).await).expect("response body should be json")
    }

    #[test]
    fn test_server_advertises_latest_protocol() {
        assert_eq!(MCP_PROTOCOL_VERSION, "2025-11-25");
    }

    #[tokio::test]
    async fn test_convert_time_matches_go_fast_time_dst_behavior() {
        let response = tools_call_response(
            Some(&json!(10)),
            &json!({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "convert_time",
                    "arguments": {
                        "time": "2025-06-21T16:00:00Z",
                        "source_timezone": "UTC",
                        "target_timezone": "America/New_York"
                    }
                },
                "id": 10
            }),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let body = response_json(response).await;
        assert_eq!(
            body["result"]["content"][0]["text"],
            "2025-06-21T12:00:00-04:00"
        );
    }

    #[tokio::test]
    async fn test_convert_time_matches_go_fast_time_half_hour_zones() {
        let response = tools_call_response(
            Some(&json!(11)),
            &json!({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "convert_time",
                    "arguments": {
                        "time": "2025-01-10 10:00:00",
                        "source_timezone": "Asia/Kolkata",
                        "target_timezone": "UTC"
                    }
                },
                "id": 11
            }),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let body = response_json(response).await;
        assert_eq!(body["result"]["content"][0]["text"], "2025-01-10T04:30:00Z");
    }

    #[tokio::test]
    async fn test_error_response_escapes_dynamic_message_text() {
        let response = error_response_with_status(
            StatusCode::BAD_REQUEST,
            Some(&json!(99)),
            -32602,
            r#"bad "message" } ,"injected":true"#,
            None,
        );

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        let body = response_json(response).await;
        assert_eq!(
            body["error"]["message"],
            r#"bad "message" } ,"injected":true"#
        );
        assert!(body["error"].get("injected").is_none());
    }

    #[tokio::test]
    async fn test_mcp_echo_rejects_delay_above_limit() {
        let response = tools_call_response(
            Some(&json!(12)),
            &json!({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {
                        "message": "hello",
                        "delay": crate::config::MAX_DELAY_MS + 1
                    }
                },
                "id": 12
            }),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let body = response_json(response).await;
        assert_eq!(body["error"]["code"], -32602);
        assert_eq!(body["error"]["message"], "delay exceeds the 60000 ms limit");
    }
}
