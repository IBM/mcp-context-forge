// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Test helper functions to reduce duplication across integration tests.

use serde_json::{Value, json};
use wiremock::matchers::{method, path, path_regex};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// Setup authentication mock that returns 200 with auth context.
pub async fn setup_auth_mock(mock_server: &MockServer, expect_calls: u64) {
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(expect_calls)
        .mount(mock_server)
        .await;
}

/// Setup authorization mock that returns 204 (authorized).
pub async fn setup_authz_mock(mock_server: &MockServer, expect_calls: u64) {
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(expect_calls)
        .mount(mock_server)
        .await;
}

/// Setup agent resolve mock that returns a ResolvedAgent pointing to the given endpoint.
pub async fn setup_resolve_mock(
    mock_server: &MockServer,
    agent_name: &str,
    agent_endpoint_url: &str,
    expect_calls: u64,
) {
    Mock::given(method("POST"))
        .and(path_regex(format!(".*/agents/{}/resolve$", agent_name)))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "agent_id": "agent-001",
            "name": agent_name,
            "endpoint_url": agent_endpoint_url,
            "agent_type": "a2a",
            "protocol_version": "1.0",
            "auth_type": null,
            "auth_value_encrypted": null,
            "auth_query_params_encrypted": null
        })))
        .expect(expect_calls)
        .mount(mock_server)
        .await;
}

/// Setup mock agent endpoint that returns a successful JSON-RPC response.
pub async fn setup_agent_endpoint_mock(
    mock_server: &MockServer,
    agent_path: &str,
    response_message: &str,
    expect_calls: u64,
) {
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "completed", "message": response_message}
        })))
        .expect(expect_calls)
        .mount(mock_server)
        .await;
}

/// Setup full trust chain mocks: authenticate, authz, resolve, and agent endpoint.
/// Returns the agent endpoint path for reference.
pub async fn setup_full_trust_chain_mocks(
    mock_server: &MockServer,
    agent_name: &str,
    response_message: &str,
) -> String {
    let agent_path = "/mock-agent-endpoint";
    let agent_endpoint_url = format!("{}{}", mock_server.uri(), agent_path);

    setup_auth_mock(mock_server, 1).await;
    setup_authz_mock(mock_server, 1).await;
    setup_resolve_mock(mock_server, agent_name, &agent_endpoint_url, 1).await;
    setup_agent_endpoint_mock(mock_server, agent_path, response_message, 1).await;

    agent_path.to_string()
}

/// Create a streaming message JSON-RPC request body.
pub fn streaming_message_json(id: i64, text: &str, role: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "method": "SendStreamingMessage",
        "id": id,
        "params": {
            "message": {
                "role": role,
                "parts": [{"text": text}]
            }
        }
    })
}

/// Create a standard SendMessage JSON-RPC request body.
pub fn send_message_json(id: i64, message: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "method": "SendMessage",
        "id": id,
        "params": {"message": message}
    })
}
