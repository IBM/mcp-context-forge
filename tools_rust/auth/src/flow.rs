// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use axum::{
    body::Bytes,
    http::{HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tracing::{error, warn};

use crate::{
    core_auth_policy,
    jwt::verify_jwt_token,
    normalize::normalize_auth_context,
    state::AppState,
    types::{AuthenticateRequest, AuthenticateResponse},
};

pub(crate) const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
pub(crate) const RUNTIME_NAME: &str = "auth";
pub(crate) const INTERNAL_RUNTIME_AUTH_HEADER: &str = "x-contextforge-mcp-runtime-auth";
const INTERNAL_RUNTIME_AUTH_CONTEXT: &str = "contextforge-internal-mcp-runtime-v1";
const DEFAULT_INTERNAL_RUNTIME_AUTH_SECRET: &str = "my-test-salt";

#[allow(clippy::result_large_err)]
pub(crate) async fn proxy_authenticate(
    state: &AppState,
    request: &AuthenticateRequest,
) -> Result<AuthenticateResponse, Response> {
    state.auth_stats.record_authenticate_request();
    if has_empty_bearer_credentials(&request.headers) {
        return Err(unauthorized_bearer_response(
            "Invalid authentication credentials",
        ));
    }
    if state.experimental_direct_auth
        && let Some(token) = bearer_token(&request.headers)
    {
        match verify_jwt_token(token, &state.jwt_verification) {
            Ok(payload) => {
                let token_use = payload.get("token_use").and_then(Value::as_str);
                let normalized_token_teams = if token_use != Some("session") {
                    Some(core_auth_policy::normalize_token_teams(&payload))
                } else {
                    None
                };
                if let Some(jti) = payload.get("jti").and_then(Value::as_str) {
                    match state.revocation_checker.is_revoked(jti).await {
                        Ok(true) => {
                            return Err(unauthorized_bearer_response_with_code(
                                "Token has been revoked",
                                "token_revoked",
                            ));
                        }
                        Ok(false) => {}
                        Err(err) => {
                            warn!(
                                "auth service token revocation check failed for jti={jti}: {err}"
                            );
                            return Err(unauthorized_bearer_response_with_code(
                                "Token validation failed",
                                "token_validation_failed",
                            ));
                        }
                    }
                }
                let email = payload
                    .get("sub")
                    .and_then(Value::as_str)
                    .or_else(|| payload.get("email").and_then(Value::as_str));
                let mut db_user_is_admin = false;
                if token_use != Some("session") && email.is_none_or(str::is_empty) {
                    return Err(unauthorized_bearer_response(
                        "Invalid authentication credentials",
                    ));
                }
                if let Some(email) = email
                    && let Ok(user) = state.user_lookup_checker.lookup_user(email).await
                {
                    match user {
                        Some(user) if !user.is_active => {
                            return Err(unauthorized_bearer_response_with_code(
                                "Account disabled",
                                "account_disabled",
                            ));
                        }
                        Some(user) => {
                            db_user_is_admin = user.is_admin;
                        }
                        None if state.require_user_in_db => {
                            return Err(unauthorized_bearer_response_with_code(
                                "User not found in database",
                                "user_not_found",
                            ));
                        }
                        None if email != state.platform_admin_email.as_ref() => {
                            return Err(unauthorized_bearer_response_with_code(
                                "User not found",
                                "user_not_found",
                            ));
                        }
                        _ => {}
                    }
                }

                if token_use != Some("session")
                    && let Some(email) = email
                {
                    let direct_auth_context = json!({
                        "email": email,
                        "teams": normalized_token_teams.clone(),
                        "is_authenticated": true,
                        "is_admin": payload.get("is_admin").and_then(Value::as_bool).unwrap_or(false),
                        "auth_method": "jwt",
                        "permission_is_admin": db_user_is_admin || payload.get("is_admin").and_then(Value::as_bool).unwrap_or(false),
                        "token_use": payload.get("token_use").cloned().unwrap_or(Value::Null),
                        "policy_inputs": {
                            "token_payload": payload.clone(),
                            "db_user_is_admin": db_user_is_admin,
                        }
                    });
                    let response = AuthenticateResponse {
                        auth_context: normalize_auth_context(direct_auth_context)?,
                    };
                    finalize_direct_response(state, request, &response).await;
                    return Ok(response);
                }
            }
            Err(_) => {
                let Some(api_token) = state
                    .api_token_lookup_checker
                    .lookup_api_token(token)
                    .await
                    .map_err(|_| {
                        unauthorized_bearer_response("Invalid authentication credentials")
                    })?
                else {
                    return Err(unauthorized_bearer_response(
                        "Invalid authentication credentials",
                    ));
                };

                if api_token.expired {
                    return Err(unauthorized_bearer_response_with_code(
                        "API token expired",
                        "api_token_expired",
                    ));
                }

                match state.revocation_checker.is_revoked(&api_token.jti).await {
                    Ok(true) => {
                        return Err(unauthorized_bearer_response_with_code(
                            "API token has been revoked",
                            "api_token_revoked",
                        ));
                    }
                    Ok(false) => {}
                    Err(_) => {
                        return Err(unauthorized_bearer_response(
                            "Invalid authentication credentials",
                        ));
                    }
                }

                let mut db_user_is_admin = false;
                if let Ok(user) = state
                    .user_lookup_checker
                    .lookup_user(&api_token.user_email)
                    .await
                {
                    match user {
                        Some(user) if !user.is_active => {
                            return Err(unauthorized_bearer_response_with_code(
                                "Account disabled",
                                "account_disabled",
                            ));
                        }
                        Some(user) => {
                            db_user_is_admin = user.is_admin;
                        }
                        None if state.require_user_in_db => {
                            return Err(unauthorized_bearer_response_with_code(
                                "User not found in database",
                                "user_not_found",
                            ));
                        }
                        None if api_token.user_email != state.platform_admin_email.as_ref() => {
                            return Err(unauthorized_bearer_response_with_code(
                                "User not found",
                                "user_not_found",
                            ));
                        }
                        _ => {}
                    }
                }

                let direct_auth_context = json!({
                    "email": api_token.user_email,
                    "teams": api_token.team_id.clone().map(|team_id| vec![team_id]).unwrap_or_default(),
                    "is_authenticated": true,
                    "is_admin": false,
                    "auth_method": "api_token",
                    "permission_is_admin": db_user_is_admin,
                    "token_use": Value::Null,
                    "jti": api_token.jti,
                    "scoped_permissions": api_token.resource_scopes,
                    "scoped_server_id": api_token.server_id,
                });
                let response = AuthenticateResponse {
                    auth_context: normalize_auth_context(direct_auth_context)?,
                };
                finalize_direct_response(state, request, &response).await;
                return Ok(response);
            }
        }
    }
    state.auth_stats.record_proxied_auth_response();
    let backend_round_trip_started = std::time::Instant::now();
    let backend_response = state
        .client
        .post(state.backend_authenticate_url())
        .header(RUNTIME_HEADER, RUNTIME_NAME)
        .header(
            HeaderName::from_static(INTERNAL_RUNTIME_AUTH_HEADER),
            internal_runtime_auth_header_value(),
        )
        .json(request)
        .send()
        .await
        .map_err(|err| {
            state
                .auth_stats
                .record_backend_round_trip(backend_round_trip_started.elapsed(), true);
            error!("auth service backend authenticate failed: {err}");
            json_response_with_code(
                StatusCode::BAD_GATEWAY,
                "backend_authenticate_failed",
                json!({"detail": "Auth service backend authenticate failed"}),
            )
        })?;
    state
        .auth_stats
        .record_backend_round_trip(backend_round_trip_started.elapsed(), false);

    let status = backend_response.status();
    if !status.is_success() {
        let body = backend_response.bytes().await.unwrap_or_else(|_| {
            Bytes::from_static(br#"{"detail":"Auth service backend authenticate failed"}"#)
        });
        let body = normalize_deny_response_body(body);
        return Err(Response::builder()
            .status(status)
            .header(axum::http::header::CONTENT_TYPE, "application/json")
            .body(axum::body::Body::from(body))
            .expect("forward backend response"));
    }

    let response_body: AuthenticateResponse = backend_response.json().await.map_err(|err| {
        error!("auth service backend authenticate decode failed: {err}");
        json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "backend_authenticate_decode_failed",
            json!({"detail": "Auth service backend authenticate decode failed"}),
        )
    })?;

    Ok(AuthenticateResponse {
        auth_context: normalize_auth_context(response_body.auth_context)?,
    })
}

async fn finalize_direct_response(
    state: &AppState,
    request: &AuthenticateRequest,
    response: &AuthenticateResponse,
) {
    state.auth_stats.record_direct_auth_response();
    if !state.shadow_compare_direct_auth {
        return;
    }
    let mismatch = match proxy_backend_once(state, request).await {
        Ok(backend_response) => normalize_auth_context(backend_response.auth_context)
            .map(|auth_context| auth_context != response.auth_context)
            .unwrap_or(true),
        Err(_) => true,
    };
    state.auth_stats.record_shadow_compare(mismatch);
}

async fn proxy_backend_once(
    state: &AppState,
    request: &AuthenticateRequest,
) -> Result<AuthenticateResponse, Response> {
    let backend_round_trip_started = std::time::Instant::now();
    let backend_response = state
        .client
        .post(state.backend_authenticate_url())
        .header(RUNTIME_HEADER, RUNTIME_NAME)
        .header(
            HeaderName::from_static(INTERNAL_RUNTIME_AUTH_HEADER),
            internal_runtime_auth_header_value(),
        )
        .json(request)
        .send()
        .await
        .map_err(|err| {
            state
                .auth_stats
                .record_backend_round_trip(backend_round_trip_started.elapsed(), true);
            error!("auth service backend authenticate failed: {err}");
            json_response_with_code(
                StatusCode::BAD_GATEWAY,
                "backend_authenticate_failed",
                json!({"detail": "Auth service backend authenticate failed"}),
            )
        })?;
    state
        .auth_stats
        .record_backend_round_trip(backend_round_trip_started.elapsed(), false);

    let status = backend_response.status();
    if !status.is_success() {
        let body = backend_response.bytes().await.unwrap_or_else(|_| {
            Bytes::from_static(br#"{"detail":"Auth service backend authenticate failed"}"#)
        });
        let body = normalize_deny_response_body(body);
        return Err(Response::builder()
            .status(status)
            .header(axum::http::header::CONTENT_TYPE, "application/json")
            .body(axum::body::Body::from(body))
            .expect("forward backend response"));
    }

    backend_response.json().await.map_err(|err| {
        error!("auth service backend authenticate decode failed: {err}");
        json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "backend_authenticate_decode_failed",
            json!({"detail": "Auth service backend authenticate decode failed"}),
        )
    })
}

fn normalize_deny_response_body(body: Bytes) -> Bytes {
    let Ok(mut payload) = serde_json::from_slice::<Value>(&body) else {
        return body;
    };
    let Some(detail) = payload
        .get("detail")
        .and_then(Value::as_str)
        .and_then(deny_detail_code)
    else {
        return body;
    };

    if let Some(payload) = payload.as_object_mut() {
        payload.insert("code".to_string(), Value::String(detail.to_string()));
        return Bytes::from(
            serde_json::to_vec(&Value::Object(payload.clone()))
                .expect("normalized deny payload serializes"),
        );
    }

    body
}

fn deny_detail_code(detail: &str) -> Option<&'static str> {
    match detail {
        "Token has been revoked" => Some("token_revoked"),
        "Account disabled" => Some("account_disabled"),
        "User not found in database" => Some("user_not_found"),
        "Invalid authentication credentials" => Some("invalid_credentials"),
        "Token validation failed" => Some("token_validation_failed"),
        "API token expired" => Some("api_token_expired"),
        "API token has been revoked" => Some("api_token_revoked"),
        _ => None,
    }
}

fn has_empty_bearer_credentials(headers: &std::collections::HashMap<String, String>) -> bool {
    bearer_token_state(headers).is_some_and(|token| token.is_empty())
}

fn bearer_token(headers: &std::collections::HashMap<String, String>) -> Option<&str> {
    bearer_token_state(headers).filter(|token| !token.is_empty())
}

fn bearer_token_state<'a>(
    headers: &'a std::collections::HashMap<String, String>,
) -> Option<&'a str> {
    headers
        .iter()
        .find(|(name, _)| name.eq_ignore_ascii_case("authorization"))
        .and_then(|(_, value)| parse_bearer_authorization(value))
}

fn parse_bearer_authorization(value: &str) -> Option<&str> {
    if value.eq_ignore_ascii_case("bearer") {
        return Some("");
    }
    let (scheme, remainder) = value.split_once(char::is_whitespace)?;
    if !scheme.eq_ignore_ascii_case("bearer") {
        return None;
    }
    Some(remainder.trim())
}

fn unauthorized_bearer_response(detail: &str) -> Response {
    unauthorized_bearer_response_with_code(detail, "invalid_credentials")
}

fn unauthorized_bearer_response_with_code(detail: &str, code: &str) -> Response {
    let mut response =
        json_response_with_code(StatusCode::UNAUTHORIZED, code, json!({ "detail": detail }));
    response.headers_mut().insert(
        axum::http::header::WWW_AUTHENTICATE,
        HeaderValue::from_static("Bearer"),
    );
    response
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    (status, axum::Json(payload)).into_response()
}

fn json_response_with_code(status: StatusCode, code: &str, payload: Value) -> Response {
    let payload = match payload {
        Value::Object(mut payload) => {
            payload.insert("code".to_string(), Value::String(code.to_string()));
            Value::Object(payload)
        }
        other => other,
    };
    json_response(status, payload)
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}

fn internal_runtime_auth_header_value() -> HeaderValue {
    let secret = std::env::var("AUTH_ENCRYPTION_SECRET")
        .unwrap_or_else(|_| DEFAULT_INTERNAL_RUNTIME_AUTH_SECRET.to_string());
    let digest = Sha256::digest(format!("{secret}:{INTERNAL_RUNTIME_AUTH_CONTEXT}").as_bytes());
    HeaderValue::from_str(&hex_encode(digest.as_ref()))
        .expect("derived internal auth header must be valid")
}
