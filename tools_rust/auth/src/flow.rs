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
    state::{AppState, CacheEntry},
    types::{AuthContext, AuthenticateRequest, AuthenticateResponse},
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
    if state.benchmark_allow_immediate && request_token(request).is_some() {
        let response = AuthenticateResponse {
            auth_context: benchmark_immediate_auth_context(state),
        };
        finalize_direct_response(state, request, &response).await;
        return Ok(response);
    }
    if has_empty_bearer_credentials(request) {
        return Err(unauthorized_bearer_response(
            "Invalid authentication credentials",
        ));
    }
    if state.experimental_direct_auth
        && let Some(token) = request_token(request)
    {
        match verify_jwt_token(token, &state.jwt_verification) {
            Ok(payload) => {
                let token_use = payload.get("token_use").and_then(Value::as_str);
                let normalized_token_teams = if token_use != Some("session") {
                    Some(core_auth_policy::normalize_token_teams(&payload))
                } else {
                    None
                };
                let email = payload
                    .get("sub")
                    .and_then(Value::as_str)
                    .or_else(|| payload.get("email").and_then(Value::as_str));
                if token_use != Some("session") && email.is_none_or(str::is_empty) {
                    return Err(unauthorized_bearer_response(
                        "Invalid authentication credentials",
                    ));
                }
                if token_use == Some("session")
                    && let (Some(jti), Some(email)) =
                        (payload.get("jti").and_then(Value::as_str), email)
                {
                    let snapshot = cached_lookup_session_auth_snapshot(state, jti, email)
                        .await
                        .map_err(|err| {
                            warn!("auth service session auth snapshot failed for jti={jti}: {err}");
                            unauthorized_bearer_response_with_code(
                                "Token validation failed",
                                "token_validation_failed",
                            )
                        })?;
                    if snapshot.revoked {
                        return Err(unauthorized_bearer_response_with_code(
                            "Token has been revoked",
                            "token_revoked",
                        ));
                    }
                    let direct_response = build_direct_session_jwt_response(
                        state,
                        email,
                        &payload,
                        snapshot.user.as_ref(),
                    )?;
                    finalize_direct_response(state, request, &direct_response).await;
                    return Ok(direct_response);
                }
                if let Some(jti) = payload.get("jti").and_then(Value::as_str) {
                    match cached_is_revoked(state, jti).await {
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
                let direct_response = build_direct_jwt_response(
                    state,
                    email,
                    token_use,
                    &payload,
                    normalized_token_teams,
                )
                .await?;
                finalize_direct_response(state, request, &direct_response).await;
                return Ok(direct_response);
            }
            Err(_) => {
                let api_snapshot = cached_lookup_api_token_auth_snapshot(state, token)
                    .await
                    .map_err(|_| {
                        unauthorized_bearer_response("Invalid authentication credentials")
                    })?;
                let Some(api_token) = api_snapshot.token else {
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

                if api_snapshot.revoked {
                    return Err(unauthorized_bearer_response_with_code(
                        "API token has been revoked",
                        "api_token_revoked",
                    ));
                }

                let db_user_is_admin = authorize_known_user_or_bootstrap(
                    state,
                    &api_token.user_email,
                    api_snapshot.user.as_ref(),
                )?;
                if let Some(team_id) = api_token.team_id.as_deref() {
                    validate_team_membership(
                        api_snapshot.user.as_ref(),
                        &api_token.user_email,
                        &[team_id.to_string()],
                    )?;
                }

                let response = AuthenticateResponse {
                    auth_context: AuthContext {
                        email: Some(api_token.user_email),
                        teams: Some(
                            api_token
                                .team_id
                                .clone()
                                .map(|team_id| vec![team_id])
                                .unwrap_or_default(),
                        ),
                        team_name: None,
                        team_id: api_token.team_id,
                        auth_method: Some("api_token".to_string()),
                        permission_is_admin: Some(db_user_is_admin),
                        is_admin: false,
                        is_authenticated: true,
                        token_use: None,
                        jti: Some(api_token.jti),
                        scoped_permissions: api_token.resource_scopes,
                        scoped_server_id: api_token.server_id,
                        policy_inputs: None,
                    },
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
        auth_context: normalize_auth_context(
            serde_json::to_value(response_body.auth_context).expect("auth context json"),
        )?,
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
        Ok(backend_response) => normalize_auth_context(
            serde_json::to_value(backend_response.auth_context).expect("auth context json"),
        )
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

async fn build_direct_jwt_response(
    state: &AppState,
    email: Option<&str>,
    token_use: Option<&str>,
    payload: &Value,
    normalized_token_teams: Option<Option<Vec<String>>>,
) -> Result<AuthenticateResponse, Response> {
    let direct_is_admin = payload
        .get("is_admin")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        || payload
            .get("user")
            .and_then(Value::as_object)
            .and_then(|user| user.get("is_admin"))
            .and_then(Value::as_bool)
            .unwrap_or(false);

    if token_use == Some("session") {
        unreachable!("session auth handled by direct session snapshot path");
    }

    let Some(email) = email else {
        return Err(unauthorized_bearer_response(
            "Invalid authentication credentials",
        ));
    };
    let user_snapshot = lookup_user_snapshot(state, email).await?;
    let db_user_is_admin = authorize_known_user_or_bootstrap(state, email, user_snapshot.as_ref())?;
    if let Some(Some(token_teams)) = normalized_token_teams.as_ref()
        && !token_teams.is_empty()
    {
        validate_team_membership(user_snapshot.as_ref(), email, token_teams)?;
    }
    let teams = normalized_token_teams.unwrap_or(None);
    let team_id = teams.as_ref().and_then(|items| match items.as_slice() {
        [single] => Some(single.clone()),
        _ => None,
    });

    Ok(AuthenticateResponse {
        auth_context: AuthContext {
            email: Some(email.to_string()),
            teams,
            team_name: derive_team_name_from_snapshot(
                user_snapshot.as_ref(),
                team_id.as_deref(),
                token_use,
            ),
            team_id,
            auth_method: Some("jwt".to_string()),
            permission_is_admin: Some(db_user_is_admin || direct_is_admin),
            is_admin: direct_is_admin,
            is_authenticated: true,
            token_use: token_use.map(str::to_string),
            jti: payload
                .get("jti")
                .and_then(Value::as_str)
                .map(str::to_string),
            scoped_permissions: derive_scoped_permissions_from_payload(payload),
            scoped_server_id: derive_scoped_server_id_from_payload(payload),
            policy_inputs: Some(json!({
                "token_payload": payload.clone(),
                "db_user_is_admin": db_user_is_admin,
                "team_names": user_snapshot
                    .as_ref()
                    .map(|snapshot| serde_json::to_value(&snapshot.team_names).expect("team names json"))
                    .unwrap_or(Value::Null),
            })),
        },
    })
}

fn build_direct_session_jwt_response(
    state: &AppState,
    email: &str,
    payload: &Value,
    user_snapshot: Option<&crate::db::UserAuthSnapshot>,
) -> Result<AuthenticateResponse, Response> {
    let direct_is_admin = payload
        .get("is_admin")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        || payload
            .get("user")
            .and_then(Value::as_object)
            .and_then(|user| user.get("is_admin"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
    let db_user_is_admin = authorize_known_user_or_bootstrap(state, email, user_snapshot)?;
    let db_teams = user_snapshot
        .filter(|snapshot| !snapshot.is_admin)
        .map(|snapshot| snapshot.team_ids.clone());
    let teams = if db_user_is_admin {
        None
    } else {
        core_auth_policy::resolve_session_teams(payload, Some(email), db_teams.as_deref())
    };
    let team_name = teams.as_ref().and_then(|items| match items.as_slice() {
        [single] => user_snapshot
            .and_then(|snapshot| snapshot.team_names.get(single))
            .cloned(),
        _ => None,
    });
    Ok(AuthenticateResponse {
        auth_context: AuthContext {
            email: Some(email.to_string()),
            teams,
            team_name,
            team_id: None,
            auth_method: Some("jwt".to_string()),
            permission_is_admin: Some(db_user_is_admin || direct_is_admin),
            is_admin: direct_is_admin,
            is_authenticated: true,
            token_use: payload
                .get("token_use")
                .and_then(Value::as_str)
                .map(str::to_string),
            jti: payload
                .get("jti")
                .and_then(Value::as_str)
                .map(str::to_string),
            scoped_permissions: derive_scoped_permissions_from_payload(payload),
            scoped_server_id: derive_scoped_server_id_from_payload(payload),
            policy_inputs: Some(json!({
                "token_payload": payload.clone(),
                "db_user_is_admin": db_user_is_admin,
                "db_teams": db_teams,
                "team_names": user_snapshot
                    .map(|snapshot| serde_json::to_value(&snapshot.team_names).expect("team names json"))
                    .unwrap_or(Value::Null),
            })),
        },
    })
}

fn benchmark_immediate_auth_context(state: &AppState) -> AuthContext {
    AuthContext {
        email: Some(state.platform_admin_email.to_string()),
        teams: None,
        team_name: None,
        team_id: None,
        auth_method: Some("benchmark_stub".to_string()),
        permission_is_admin: Some(true),
        is_admin: true,
        is_authenticated: true,
        token_use: Some("session".to_string()),
        jti: Some("benchmark-immediate".to_string()),
        scoped_permissions: Vec::new(),
        scoped_server_id: None,
        policy_inputs: None,
    }
}

fn derive_team_name_from_snapshot(
    user_snapshot: Option<&crate::db::UserAuthSnapshot>,
    primary_team_id: Option<&str>,
    token_use: Option<&str>,
) -> Option<String> {
    let primary_team_id = primary_team_id?;
    if token_use == Some("session") {
        return None;
    }
    user_snapshot
        .and_then(|snapshot| snapshot.team_names.get(primary_team_id))
        .cloned()
}

fn derive_scoped_permissions_from_payload(payload: &Value) -> Vec<String> {
    payload
        .get("scopes")
        .and_then(|value| match value {
            Value::Object(object) => object.get("permissions"),
            other => Some(other),
        })
        .or_else(|| payload.get("resource_scopes"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn derive_scoped_server_id_from_payload(payload: &Value) -> Option<String> {
    payload
        .get("scopes")
        .and_then(|value| match value {
            Value::Object(object) => object.get("server_id"),
            _ => None,
        })
        .or_else(|| payload.get("server_id"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

async fn lookup_user_snapshot(
    state: &AppState,
    email: &str,
) -> Result<Option<crate::db::UserAuthSnapshot>, Response> {
    cached_lookup_user_snapshot(state, email)
        .await
        .map_err(|err| {
            error!("auth service user snapshot lookup failed for {email}: {err}");
            json_response_with_code(
                StatusCode::SERVICE_UNAVAILABLE,
                "auth_dependency_failed",
                json!({"detail": "Auth service user snapshot lookup failed"}),
            )
        })
}

async fn cached_is_revoked(state: &AppState, jti: &str) -> Result<bool, String> {
    let now = std::time::Instant::now();
    if let Ok(cache) = state.revocation_cache.read()
        && let Some(entry) = cache.get(jti)
        && entry.expires_at > now
    {
        state.auth_stats.record_revocation_cache_hit();
        return Ok(entry.value);
    }

    state.auth_stats.record_revocation_cache_miss();
    let revoked = state.revocation_checker.is_revoked(jti).await?;
    if let Ok(mut cache) = state.revocation_cache.write() {
        cache.insert(
            jti.to_string(),
            CacheEntry {
                expires_at: now + state.revocation_cache_ttl,
                value: revoked,
            },
        );
    }
    Ok(revoked)
}

async fn cached_lookup_user_snapshot(
    state: &AppState,
    email: &str,
) -> Result<Option<crate::db::UserAuthSnapshot>, String> {
    let now = std::time::Instant::now();
    if let Ok(cache) = state.user_snapshot_cache.read()
        && let Some(entry) = cache.get(email)
        && entry.expires_at > now
    {
        state.auth_stats.record_user_snapshot_cache_hit();
        return Ok(entry.value.clone());
    }

    state.auth_stats.record_user_snapshot_cache_miss();
    let snapshot = state
        .user_auth_snapshot_checker
        .lookup_user_auth_snapshot(email)
        .await?;
    if let Ok(mut cache) = state.user_snapshot_cache.write() {
        cache.insert(
            email.to_string(),
            CacheEntry {
                expires_at: now + state.user_snapshot_cache_ttl,
                value: snapshot.clone(),
            },
        );
    }
    Ok(snapshot)
}

async fn cached_lookup_session_auth_snapshot(
    state: &AppState,
    jti: &str,
    email: &str,
) -> Result<crate::db::SessionAuthSnapshot, String> {
    let cache_key = format!("{jti}:{email}");
    let now = std::time::Instant::now();
    if let Ok(cache) = state.session_auth_snapshot_cache.read()
        && let Some(entry) = cache.get(&cache_key)
        && entry.expires_at > now
    {
        state.auth_stats.record_session_auth_snapshot_cache_hit();
        return Ok(entry.value.clone());
    }

    state.auth_stats.record_session_auth_snapshot_cache_miss();
    let snapshot = state
        .session_auth_snapshot_checker
        .lookup_session_auth_snapshot(jti, email)
        .await?;
    if let Ok(mut cache) = state.session_auth_snapshot_cache.write() {
        cache.insert(
            cache_key,
            CacheEntry {
                expires_at: now + state.session_auth_snapshot_cache_ttl,
                value: snapshot.clone(),
            },
        );
    }
    Ok(snapshot)
}

async fn cached_lookup_api_token_auth_snapshot(
    state: &AppState,
    token: &str,
) -> Result<crate::db::ApiTokenAuthSnapshot, String> {
    let digest = sha256_hex(token);
    let now = std::time::Instant::now();
    if let Ok(cache) = state.api_token_auth_snapshot_cache.read()
        && let Some(entry) = cache.get(&digest)
        && entry.expires_at > now
    {
        state.auth_stats.record_api_token_auth_snapshot_cache_hit();
        return Ok(entry.value.clone());
    }

    state.auth_stats.record_api_token_auth_snapshot_cache_miss();
    let snapshot = state
        .api_token_auth_snapshot_checker
        .lookup_api_token_auth_snapshot(token)
        .await?;
    if let Ok(mut cache) = state.api_token_auth_snapshot_cache.write() {
        cache.insert(
            digest,
            CacheEntry {
                expires_at: now + state.api_token_auth_snapshot_cache_ttl,
                value: snapshot.clone(),
            },
        );
    }
    Ok(snapshot)
}

fn authorize_known_user_or_bootstrap(
    state: &AppState,
    email: &str,
    user_snapshot: Option<&crate::db::UserAuthSnapshot>,
) -> Result<bool, Response> {
    match user_snapshot {
        Some(snapshot) if !snapshot.is_active => Err(unauthorized_bearer_response_with_code(
            "Account disabled",
            "account_disabled",
        )),
        Some(snapshot) => Ok(snapshot.is_admin),
        None if state.require_user_in_db => Err(unauthorized_bearer_response_with_code(
            "User not found in database",
            "user_not_found",
        )),
        None if email == state.platform_admin_email.as_ref() => Ok(true),
        None => Err(unauthorized_bearer_response_with_code(
            "User not found",
            "user_not_found",
        )),
    }
}

fn validate_team_membership(
    user_snapshot: Option<&crate::db::UserAuthSnapshot>,
    email: &str,
    token_teams: &[String],
) -> Result<(), Response> {
    let Some(user_snapshot) = user_snapshot else {
        return Ok(());
    };
    if user_snapshot.is_admin || token_teams.is_empty() {
        return Ok(());
    }
    if token_teams.iter().all(|team_id| {
        user_snapshot
            .team_ids
            .iter()
            .any(|candidate| candidate == team_id)
    }) {
        return Ok(());
    }

    warn!("auth service rejected token team membership for {email}");
    Err(json_response_with_code(
        StatusCode::FORBIDDEN,
        "token_team_membership_invalid",
        json!({"detail": "Token invalid: User is no longer a member of the associated team"}),
    ))
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

fn sha256_hex(value: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(value.as_bytes());
    format!("{:x}", digest.finalize())
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
        "Token invalid: User is no longer a member of the associated team" => {
            Some("token_team_membership_invalid")
        }
        _ => None,
    }
}

fn request_token(request: &AuthenticateRequest) -> Option<&str> {
    cookie_token(request).or_else(|| bearer_token(request))
}

fn has_empty_bearer_credentials(request: &AuthenticateRequest) -> bool {
    bearer_token_state(request).is_some_and(|token| token.is_empty())
}

fn bearer_token(request: &AuthenticateRequest) -> Option<&str> {
    bearer_token_state(request).filter(|token| !token.is_empty())
}

fn bearer_token_state<'a>(request: &'a AuthenticateRequest) -> Option<&'a str> {
    request
        .authorization
        .as_deref()
        .and_then(parse_bearer_authorization)
}

fn cookie_token<'a>(request: &'a AuthenticateRequest) -> Option<&'a str> {
    let cookie_header = request.cookie.as_deref()?;
    for pair in cookie_header.split(';') {
        let (name, value) = pair.trim().split_once('=')?;
        if matches!(name, "jwt_token" | "access_token") {
            let value = value.trim();
            if !value.is_empty() {
                return Some(value);
            }
        }
    }
    None
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
