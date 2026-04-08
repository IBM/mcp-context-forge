
use super::{
    ApiTokenLookupChecker, ApiTokenLookupRecord, AppState, AuthenticateRequest,
    INTERNAL_RUNTIME_AUTH_HEADER, JwtVerificationConfig, JwtVerifyError, RUNTIME_HEADER,
    RUNTIME_NAME, RevocationChecker, UserLookupChecker, UserLookupRecord, build_router,
    normalize_auth_context, proxy_authenticate, verify_backend_readiness, verify_jwt_token,
};
use crate::config::AuthConfig;
use async_trait::async_trait;
use axum::{
    Json, Router,
    http::{HeaderMap, StatusCode},
    routing::{get, post},
};
use jsonwebtoken::{EncodingKey, Header, encode};
use serde_json::json;
use std::{sync::Arc, time::Duration};

async fn spawn_router(router: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind listener");
    let addr = listener.local_addr().expect("local addr");
    tokio::spawn(async move {
        axum::serve(listener, router).await.expect("serve router");
    });
    format!("http://{addr}")
}

fn test_config(backend_authenticate_url: String) -> AuthConfig {
    AuthConfig {
        database_url: None,
        backend_authenticate_url,
        backend_health_url: None,
        listen_http: "127.0.0.1:8788".to_string(),
        request_timeout_ms: 30_000,
        db_pool_max_size: 8,
        experimental_direct_auth: true,
        shadow_compare_direct_auth: false,
        log_filter: "error".to_string(),
        jwt_secret_key: "this-is-a-long-test-secret-key-32chars".to_string(),
        jwt_algorithm: "HS256".to_string(),
        jwt_audience: "mcpgateway-api".to_string(),
        jwt_issuer: "mcpgateway".to_string(),
        jwt_audience_verification: true,
        jwt_issuer_verification: true,
        require_token_expiration: true,
        require_jti: true,
        require_user_in_db: false,
        platform_admin_email: "admin@example.com".to_string(),
    }
}

fn jwt_verification_config() -> JwtVerificationConfig {
    JwtVerificationConfig {
        secret: "this-is-a-long-test-secret-key-32chars".to_string(),
        algorithm: "HS256".to_string(),
        audience: "mcpgateway-api".to_string(),
        issuer: "mcpgateway".to_string(),
        verify_audience: true,
        verify_issuer: true,
        require_expiration: true,
        require_jti: true,
    }
}

struct FixedRevocationChecker {
    result: Result<bool, String>,
}

#[async_trait]
impl RevocationChecker for FixedRevocationChecker {
    async fn is_revoked(&self, _jti: &str) -> Result<bool, String> {
        self.result.clone()
    }
}

struct FixedUserLookupChecker {
    result: Result<Option<UserLookupRecord>, String>,
}

#[async_trait]
impl UserLookupChecker for FixedUserLookupChecker {
    async fn lookup_user(&self, _email: &str) -> Result<Option<UserLookupRecord>, String> {
        self.result.clone()
    }
}

struct FixedApiTokenLookupChecker {
    result: Result<Option<ApiTokenLookupRecord>, String>,
}

#[async_trait]
impl ApiTokenLookupChecker for FixedApiTokenLookupChecker {
    async fn lookup_api_token(&self, _token: &str) -> Result<Option<ApiTokenLookupRecord>, String> {
        self.result.clone()
    }
}

#[test]
fn verify_jwt_token_accepts_valid_hs256_token() {
    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let payload = verify_jwt_token(&token, &jwt_verification_config()).expect("valid jwt");

    assert_eq!(payload["sub"], "trusted@example.com");
    assert_eq!(payload["jti"], "jwt-123");
}

#[test]
fn verify_jwt_token_rejects_missing_required_jti() {
    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let error = verify_jwt_token(&token, &jwt_verification_config()).expect_err("missing jti");

    assert_eq!(error, JwtVerifyError::MissingRequiredJti);
}

#[test]
fn verify_jwt_token_rejects_invalid_audience() {
    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "wrong-audience",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let error = verify_jwt_token(&token, &jwt_verification_config()).expect_err("invalid audience");

    assert_eq!(error, JwtVerifyError::InvalidToken);
}

#[tokio::test]
async fn proxy_authenticate_rejects_non_session_jwt_without_principal_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("non-session jwt without principal should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(
        response
            .headers()
            .get("www-authenticate")
            .and_then(|v| v.to_str().ok()),
        Some("Bearer")
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Invalid authentication credentials");
    assert_eq!(payload["code"], "invalid_credentials");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for jwt without principal"
    );
}

#[test]
fn normalize_auth_context_filters_team_entries() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["team-a", {"id": "team-b"}, {"name": "skip"}, 42],
        "is_authenticated": true,
        "is_admin": false
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a", "team-b"],
            "permission_is_admin": false,
            "is_authenticated": true,
            "is_admin": false
        })
    );
}

#[test]
fn normalize_auth_context_recomputes_non_session_teams_from_policy_inputs() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "team_id": "stale-team",
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "api",
        "policy_inputs": {
            "token_payload": {
                "teams": ["team-a", {"id": "team-b"}, {"name": "skip"}]
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a", "team-b"],
            "team_id": null,
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "api",
            "policy_inputs": {
                "token_payload": {
                    "teams": ["team-a", {"id": "team-b"}, {"name": "skip"}]
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_recomputes_session_teams_from_policy_inputs() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "team_id": "stale-team",
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": ["team-a", "team-b"]
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": null,
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "session",
            "policy_inputs": {
                "token_payload": {
                    "teams": ["team-a"]
                },
                "db_teams": ["team-a", "team-b"]
            }
        })
    );
}

#[test]
fn normalize_auth_context_uses_db_admin_bypass_for_session_tokens() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "team_name": "stale-name",
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "db_user_is_admin": true,
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": ["team-a", "team-b"],
            "team_names": {
                "team-a": "Alpha Team"
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": null,
            "team_name": null,
            "permission_is_admin": true,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "session",
            "policy_inputs": {
                "db_user_is_admin": true,
                "token_payload": {
                    "teams": ["team-a"]
                },
                "db_teams": ["team-a", "team-b"],
                "team_names": {
                    "team-a": "Alpha Team"
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_rejects_invalid_session_db_teams_shape() {
    let response = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": "team-a"
        }
    }))
    .expect_err("invalid db_teams shape");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let runtime = tokio::runtime::Runtime::new().expect("runtime");
    let payload = runtime.block_on(async {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        serde_json::from_slice::<serde_json::Value>(&body).expect("payload json")
    });
    assert_eq!(
        payload["detail"],
        "Auth service received invalid auth context"
    );
    assert_eq!(payload["code"], "invalid_auth_context");
}

#[test]
fn normalize_auth_context_rejects_missing_db_teams_for_non_admin_session_tokens() {
    let response = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "db_user_is_admin": false,
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": null
        }
    }))
    .expect_err("non-admin session tokens require authoritative db_teams");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let runtime = tokio::runtime::Runtime::new().expect("runtime");
    let payload = runtime.block_on(async {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        serde_json::from_slice::<serde_json::Value>(&body).expect("payload json")
    });
    assert_eq!(
        payload["detail"],
        "Auth service received invalid auth context"
    );
    assert_eq!(payload["code"], "invalid_auth_context");
}

#[test]
fn normalize_auth_context_session_missing_email_forces_public_only_scope() {
    let normalized = normalize_auth_context(json!({
        "email": null,
        "teams": ["stale-team"],
        "team_name": "stale-name",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "db_user_is_admin": true,
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": ["team-a", "team-b"],
            "team_names": {
                "team-a": "Alpha Team"
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": null,
            "teams": [],
            "team_name": null,
            "permission_is_admin": true,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "session",
            "policy_inputs": {
                "db_user_is_admin": true,
                "token_payload": {
                    "teams": ["team-a"]
                },
                "db_teams": ["team-a", "team-b"],
                "team_names": {
                    "team-a": "Alpha Team"
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_rejects_authenticated_non_session_context_without_email() {
    let response = normalize_auth_context(json!({
        "email": null,
        "teams": ["team-a"],
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "api",
        "policy_inputs": {
            "token_payload": {
                "teams": ["team-a"]
            }
        }
    }))
    .expect_err("authenticated non-session context requires email");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let runtime = tokio::runtime::Runtime::new().expect("runtime");
    let payload = runtime.block_on(async {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        serde_json::from_slice::<serde_json::Value>(&body).expect("payload json")
    });
    assert_eq!(
        payload["detail"],
        "Auth service received invalid auth context"
    );
    assert_eq!(payload["code"], "invalid_auth_context");
}

#[test]
fn normalize_auth_context_rejects_email_mismatch_with_token_payload() {
    let response = normalize_auth_context(json!({
        "email": "runtime@example.com",
        "teams": ["team-a"],
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "api",
        "policy_inputs": {
            "token_payload": {
                "sub": "token@example.com",
                "teams": ["team-a"]
            }
        }
    }))
    .expect_err("token payload principal mismatch should fail closed");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let runtime = tokio::runtime::Runtime::new().expect("runtime");
    let payload = runtime.block_on(async {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        serde_json::from_slice::<serde_json::Value>(&body).expect("payload json")
    });
    assert_eq!(
        payload["detail"],
        "Auth service received invalid auth context"
    );
    assert_eq!(payload["code"], "invalid_auth_context");
}

#[test]
fn normalize_auth_context_sets_team_id_for_single_non_session_team() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["stale-team"],
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "api",
        "policy_inputs": {
            "token_payload": {
                "teams": [{
                    "id": "team-a",
                    "name": "Alpha Team"
                }]
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": "team-a",
            "team_name": "Alpha Team",
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "api",
            "policy_inputs": {
                "token_payload": {
                    "teams": [{
                        "id": "team-a",
                        "name": "Alpha Team"
                    }]
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_prefers_preresolved_session_team_name() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["team-a"],
        "team_name": "stale-name",
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "session",
        "policy_inputs": {
            "token_payload": {
                "teams": ["team-a"]
            },
            "db_teams": ["team-a", "team-b"],
            "team_names": {
                "team-a": "Alpha Team"
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_name": "Alpha Team",
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "session",
            "policy_inputs": {
                "token_payload": {
                    "teams": ["team-a"]
                },
                "db_teams": ["team-a", "team-b"],
                "team_names": {
                    "team-a": "Alpha Team"
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_recomputes_scoped_permissions_and_server_id() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": ["team-a"],
        "scoped_permissions": ["stale.permission"],
        "scoped_server_id": "stale-server",
        "permission_is_admin": false,
        "auth_method": "stale",
        "is_authenticated": true,
        "is_admin": false,
        "token_use": "api",
        "policy_inputs": {
            "db_user_is_admin": true,
            "token_payload": {
                "teams": [{
                    "id": "team-a",
                    "name": "Alpha Team"
                }],
                "scopes": {
                    "permissions": ["tools.execute", " resources.read ", 4],
                    "server_id": "server-123"
                }
            }
        }
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": "team-a",
            "team_name": "Alpha Team",
            "scoped_permissions": ["tools.execute", "resources.read"],
            "scoped_server_id": "server-123",
            "permission_is_admin": true,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": "api",
            "policy_inputs": {
                "db_user_is_admin": true,
                "token_payload": {
                    "teams": [{
                        "id": "team-a",
                        "name": "Alpha Team"
                    }],
                    "scopes": {
                        "permissions": ["tools.execute", " resources.read ", 4],
                        "server_id": "server-123"
                    }
                }
            }
        })
    );
}

#[test]
fn normalize_auth_context_rejects_invalid_team_shape() {
    let response = normalize_auth_context(json!({
        "teams": "team-a"
    }))
    .expect_err("invalid teams shape");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let runtime = tokio::runtime::Runtime::new().expect("runtime");
    let payload = runtime.block_on(async {
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("read body");
        serde_json::from_slice::<serde_json::Value>(&body).expect("payload json")
    });
    assert_eq!(
        payload["detail"],
        "Auth service received invalid auth context"
    );
    assert_eq!(payload["code"], "invalid_auth_context");
}

#[test]
fn normalize_auth_context_applies_secure_default_for_non_admin_null_teams() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "teams": null,
        "is_authenticated": true,
        "is_admin": false
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": [],
            "permission_is_admin": false,
            "is_authenticated": true,
            "is_admin": false
        })
    );
}

#[test]
fn normalize_auth_context_applies_secure_default_for_non_admin_missing_teams() {
    let normalized = normalize_auth_context(json!({
        "email": "trusted@example.com",
        "is_authenticated": true,
        "is_admin": false
    }))
    .expect("normalized auth context");

    assert_eq!(
        normalized,
        json!({
            "email": "trusted@example.com",
            "teams": [],
            "permission_is_admin": false,
            "is_authenticated": true,
            "is_admin": false
        })
    );
}

#[tokio::test]
async fn proxy_authenticate_passes_through_backend_response() {
    let captured_headers = std::sync::Arc::new(std::sync::Mutex::new(None::<HeaderMap>));
    let captured_headers_auth = captured_headers.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move |headers: HeaderMap| {
            let captured_headers_auth = captured_headers_auth.clone();
            async move {
                *captured_headers_auth.lock().expect("lock") = Some(headers);
                Json(json!({
                    "authContext": {
                        "email": "trusted@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect("proxy authenticate");

    assert_eq!(
        response.auth_context,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": "team-a",
            "permission_is_admin": false,
            "is_authenticated": true,
            "is_admin": false
        })
    );

    let captured_headers = captured_headers
        .lock()
        .expect("lock")
        .clone()
        .expect("captured headers");
    assert_eq!(
        captured_headers
            .get(RUNTIME_HEADER)
            .and_then(|value| value.to_str().ok()),
        Some(RUNTIME_NAME)
    );
    assert!(captured_headers.contains_key(INTERNAL_RUNTIME_AUTH_HEADER));
}

#[tokio::test]
async fn build_router_exposes_health() {
    let backend_url = "http://127.0.0.1:4444/_internal/core/auth/authenticate".to_string();
    let app = build_router(AppState::new(&test_config(backend_url.clone())).expect("state"));
    let base_url = spawn_router(app).await;
    let response = reqwest::get(format!("{base_url}/healthz"))
        .await
        .expect("health response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload: serde_json::Value = response.json().await.expect("health json");
    assert_eq!(payload["status"], "ok");
    assert_eq!(payload["backend_authenticate_url"], backend_url);
    assert_eq!(payload["backend_health_url"], serde_json::Value::Null);
    assert_eq!(payload["experimental_direct_auth"], true);
    assert_eq!(payload["shadow_compare_direct_auth"], false);
    assert_eq!(payload["auth_stats"]["authenticate_requests"], 0);
    assert_eq!(payload["auth_stats"]["direct_auth_responses"], 0);
    assert_eq!(payload["auth_stats"]["proxied_auth_responses"], 0);
    assert_eq!(payload["auth_stats"]["backend_round_trips"], 0);
    assert_eq!(payload["auth_stats"]["backend_round_trip_total_ms"], 0);
    assert_eq!(payload["auth_stats"]["backend_round_trip_max_ms"], 0);
    assert_eq!(payload["auth_stats"]["backend_failures"], 0);
    assert_eq!(payload["auth_stats"]["shadow_compare_requests"], 0);
    assert_eq!(payload["auth_stats"]["shadow_compare_mismatches"], 0);
}

#[tokio::test]
async fn proxy_authenticate_updates_auth_stats() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move {
            tokio::time::sleep(Duration::from_millis(15)).await;
            Json(json!({
                "authContext": {
                    "email": "trusted@example.com",
                    "teams": ["team-a"],
                    "is_authenticated": true,
                    "is_admin": false
                }
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let _response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect("proxy authenticate");

    let app = build_router(state);
    let base_url = spawn_router(app).await;
    let response = reqwest::get(format!("{base_url}/healthz"))
        .await
        .expect("health response");
    let payload: serde_json::Value = response.json().await.expect("health json");
    assert_eq!(payload["auth_stats"]["authenticate_requests"], 1);
    assert_eq!(payload["auth_stats"]["direct_auth_responses"], 0);
    assert_eq!(payload["auth_stats"]["proxied_auth_responses"], 1);
    assert_eq!(payload["auth_stats"]["backend_round_trips"], 1);
    assert_eq!(payload["auth_stats"]["backend_failures"], 0);
    assert!(
        payload["auth_stats"]["backend_round_trip_total_ms"]
            .as_u64()
            .unwrap_or(0)
            >= 15
    );
    assert!(
        payload["auth_stats"]["backend_round_trip_max_ms"]
            .as_u64()
            .unwrap_or(0)
            >= 15
    );
    assert_eq!(payload["auth_stats"]["shadow_compare_requests"], 0);
    assert_eq!(payload["auth_stats"]["shadow_compare_mismatches"], 0);
}

#[tokio::test]
async fn proxy_authenticate_normalizes_known_deny_detail_codes() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move {
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"detail": "Token has been revoked"})),
            )
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect_err("proxy should preserve deny as error response");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("deny payload json");
    assert_eq!(payload["detail"], "Token has been revoked");
    assert_eq!(payload["code"], "token_revoked");
}

#[tokio::test]
async fn proxy_authenticate_normalizes_token_validation_failure_code() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move {
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"detail": "Token validation failed"})),
            )
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect_err("unauthorized");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Token validation failed");
    assert_eq!(payload["code"], "token_validation_failed");
}

#[tokio::test]
async fn proxy_authenticate_rejects_empty_bearer_credentials_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), "Bearer".to_string())]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("empty bearer credentials should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(
        response
            .headers()
            .get("www-authenticate")
            .and_then(|v| v.to_str().ok()),
        Some("Bearer")
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Invalid authentication credentials");
    assert_eq!(payload["code"], "invalid_credentials");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for empty bearer credentials"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_empty_bearer_credentials_case_insensitively() {
    let state = AppState::new(&test_config(
        "http://127.0.0.1:9/_internal/core/auth/authenticate".to_string(),
    ))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), "bearer ".to_string())]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("empty bearer credentials should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Invalid authentication credentials");
    assert_eq!(payload["code"], "invalid_credentials");
}

#[tokio::test]
async fn proxy_authenticate_rejects_invalid_bearer_jwt_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [(
                "authorization".to_string(),
                "Bearer definitely-not-a-jwt".to_string(),
            )]
            .into_iter()
            .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("invalid bearer jwt should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(
        response
            .headers()
            .get("www-authenticate")
            .and_then(|v| v.to_str().ok()),
        Some("Bearer")
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Invalid authentication credentials");
    assert_eq!(payload["code"], "invalid_credentials");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for invalid bearer jwt"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_revoked_bearer_jwt_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_revocation_checker(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(true) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "revoked-jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("revoked bearer jwt should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(
        response
            .headers()
            .get("www-authenticate")
            .and_then(|v| v.to_str().ok()),
        Some("Bearer")
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Token has been revoked");
    assert_eq!(payload["code"], "token_revoked");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for revoked bearer jwt"
    );
}

#[tokio::test]
async fn proxy_authenticate_fails_secure_when_revocation_check_errors_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_revocation_checker(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker {
            result: Err("database unavailable".to_string()),
        }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("revocation check errors should fail secure");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert_eq!(
        response
            .headers()
            .get("www-authenticate")
            .and_then(|v| v.to_str().ok()),
        Some("Bearer")
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Token validation failed");
    assert_eq!(payload["code"], "token_validation_failed");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called when revocation check errors"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_missing_user_when_require_user_in_db_is_enabled_without_backend_call()
 {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let mut config = test_config(format!("{backend_url}/_internal/core/auth/authenticate"));
    config.require_user_in_db = true;
    let state = AppState::with_checkers(
        &config,
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker { result: Ok(None) }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("missing user should fail closed when require_user_in_db is enabled");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "User not found in database");
    assert_eq!(payload["code"], "user_not_found");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for missing user in strict mode"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_disabled_user_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": [],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker {
            result: Ok(Some(UserLookupRecord {
                is_active: false,
                is_admin: false,
            })),
        }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("disabled user should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "Account disabled");
    assert_eq!(payload["code"], "account_disabled");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for disabled user"
    );
}

#[tokio::test]
async fn proxy_authenticate_returns_direct_public_only_jwt_auth_context_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker {
            result: Ok(Some(UserLookupRecord {
                is_active: true,
                is_admin: false,
            })),
        }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect("direct public-only jwt auth context");

    assert_eq!(
        response.auth_context,
        json!({
            "email": "trusted@example.com",
            "teams": [],
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": null,
            "policy_inputs": {
                "token_payload": {
                    "sub": "trusted@example.com",
                    "jti": "jwt-123",
                    "aud": "mcpgateway-api",
                    "iss": "mcpgateway",
                    "exp": 4_102_444_800i64
                },
                "db_user_is_admin": false
            }
        })
    );
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for direct public-only jwt auth"
    );
}

#[tokio::test]
async fn proxy_authenticate_returns_direct_team_scoped_jwt_auth_context_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker {
            result: Ok(Some(UserLookupRecord {
                is_active: true,
                is_admin: false,
            })),
        }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64,
            "teams": [{
                "id": "team-a",
                "name": "Alpha Team"
            }],
            "scopes": {
                "permissions": ["tools.execute", " resources.read "],
                "server_id": "server-123"
            }
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect("direct team-scoped jwt auth context");

    assert_eq!(
        response.auth_context,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": "team-a",
            "team_name": "Alpha Team",
            "permission_is_admin": false,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": null,
            "scoped_permissions": ["tools.execute", "resources.read"],
            "scoped_server_id": "server-123",
            "policy_inputs": {
                "token_payload": {
                    "sub": "trusted@example.com",
                    "jti": "jwt-123",
                    "aud": "mcpgateway-api",
                    "iss": "mcpgateway",
                    "exp": 4_102_444_800i64,
                    "teams": [{
                        "id": "team-a",
                        "name": "Alpha Team"
                    }],
                    "scopes": {
                        "permissions": ["tools.execute", " resources.read "],
                        "server_id": "server-123"
                    }
                },
                "db_user_is_admin": false
            }
        })
    );
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for direct team-scoped jwt auth"
    );
}

#[tokio::test]
async fn proxy_authenticate_returns_direct_platform_admin_bootstrap_auth_context_without_backend_call()
 {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker { result: Ok(None) }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "admin@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64,
            "is_admin": true,
            "teams": null
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect("direct platform admin bootstrap auth context");

    assert_eq!(
        response.auth_context,
        json!({
            "email": "admin@example.com",
            "teams": null,
            "permission_is_admin": true,
            "auth_method": "jwt",
            "is_authenticated": true,
            "is_admin": true,
            "token_use": null,
            "policy_inputs": {
                "token_payload": {
                    "sub": "admin@example.com",
                    "jti": "jwt-123",
                    "aud": "mcpgateway-api",
                    "iss": "mcpgateway",
                    "exp": 4_102_444_800i64,
                    "is_admin": true,
                    "teams": null
                },
                "db_user_is_admin": false
            }
        })
    );
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for direct platform-admin bootstrap auth"
    );
}

#[tokio::test]
async fn proxy_authenticate_returns_direct_api_token_auth_context_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker {
            result: Ok(Some(UserLookupRecord {
                is_active: true,
                is_admin: false,
            })),
        }),
        Arc::new(FixedApiTokenLookupChecker {
            result: Ok(Some(ApiTokenLookupRecord {
                user_email: "trusted@example.com".to_string(),
                jti: "api-token-jti-123".to_string(),
                team_id: Some("team-a".to_string()),
                server_id: Some("server-123".to_string()),
                resource_scopes: vec!["tools.execute".to_string(), "resources.read".to_string()],
                expired: false,
            })),
        }),
    )
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [(
                "authorization".to_string(),
                "Bearer opaque-api-token".to_string(),
            )]
            .into_iter()
            .collect(),
            client_ip: None,
        },
    )
    .await
    .expect("direct api token auth context");

    assert_eq!(
        response.auth_context,
        json!({
            "email": "trusted@example.com",
            "teams": ["team-a"],
            "team_id": "team-a",
            "permission_is_admin": false,
            "auth_method": "api_token",
            "is_authenticated": true,
            "is_admin": false,
            "token_use": null,
            "jti": "api-token-jti-123",
            "scoped_permissions": ["tools.execute", "resources.read"],
            "scoped_server_id": "server-123"
        })
    );
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for direct api-token auth"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_expired_api_token_with_distinct_code_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker { result: Ok(None) }),
        Arc::new(FixedApiTokenLookupChecker {
            result: Ok(Some(ApiTokenLookupRecord {
                user_email: "trusted@example.com".to_string(),
                jti: "api-token-jti-123".to_string(),
                team_id: Some("team-a".to_string()),
                server_id: None,
                resource_scopes: Vec::new(),
                expired: true,
            })),
        }),
    )
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [(
                "authorization".to_string(),
                "Bearer opaque-api-token".to_string(),
            )]
            .into_iter()
            .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("expired api token should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "API token expired");
    assert_eq!(payload["code"], "api_token_expired");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for expired api token"
    );
}

#[tokio::test]
async fn proxy_authenticate_rejects_revoked_api_token_with_distinct_code_without_backend_call() {
    let called = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called_clone = called.clone();
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(move || {
            let called = called_clone.clone();
            async move {
                called.store(true, std::sync::atomic::Ordering::Relaxed);
                Json(json!({
                    "authContext": {
                        "email": "should-not-be-called@example.com",
                        "teams": ["unexpected-team"],
                        "is_authenticated": true,
                        "is_admin": false
                    }
                }))
            }
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::with_checkers(
        &test_config(format!("{backend_url}/_internal/core/auth/authenticate")),
        Arc::new(FixedRevocationChecker { result: Ok(true) }),
        Arc::new(FixedUserLookupChecker { result: Ok(None) }),
        Arc::new(FixedApiTokenLookupChecker {
            result: Ok(Some(ApiTokenLookupRecord {
                user_email: "trusted@example.com".to_string(),
                jti: "api-token-jti-123".to_string(),
                team_id: Some("team-a".to_string()),
                server_id: None,
                resource_scopes: Vec::new(),
                expired: false,
            })),
        }),
    )
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [(
                "authorization".to_string(),
                "Bearer opaque-api-token".to_string(),
            )]
            .into_iter()
            .collect(),
            client_ip: None,
        },
    )
    .await
    .expect_err("revoked api token should fail closed");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("payload json");
    assert_eq!(payload["detail"], "API token has been revoked");
    assert_eq!(payload["code"], "api_token_revoked");
    assert!(
        !called.load(std::sync::atomic::Ordering::Relaxed),
        "backend should not be called for revoked api token"
    );
}

#[tokio::test]
async fn proxy_authenticate_records_shadow_compare_mismatch_for_direct_auth() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move {
            Json(json!({
                "authContext": {
                    "email": "trusted@example.com",
                    "teams": ["different-team"],
                    "is_authenticated": true,
                    "is_admin": false
                }
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;
    let mut config = test_config(format!("{backend_url}/_internal/core/auth/authenticate"));
    config.shadow_compare_direct_auth = true;
    let state = AppState::with_checkers(
        &config,
        Arc::new(FixedRevocationChecker { result: Ok(false) }),
        Arc::new(FixedUserLookupChecker {
            result: Ok(Some(UserLookupRecord {
                is_active: true,
                is_admin: false,
            })),
        }),
        Arc::new(FixedApiTokenLookupChecker { result: Ok(None) }),
    )
    .expect("state");

    let token = encode(
        &Header::default(),
        &json!({
            "sub": "trusted@example.com",
            "jti": "jwt-123",
            "aud": "mcpgateway-api",
            "iss": "mcpgateway",
            "exp": 4_102_444_800i64
        }),
        &EncodingKey::from_secret(b"this-is-a-long-test-secret-key-32chars"),
    )
    .expect("encode jwt");

    let _response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: [("authorization".to_string(), format!("Bearer {token}"))]
                .into_iter()
                .collect(),
            client_ip: None,
        },
    )
    .await
    .expect("direct auth");

    let app = build_router(state);
    let base_url = spawn_router(app).await;
    let response = reqwest::get(format!("{base_url}/healthz"))
        .await
        .expect("health response");
    let payload: serde_json::Value = response.json().await.expect("health json");
    assert_eq!(payload["auth_stats"]["direct_auth_responses"], 1);
    assert_eq!(payload["auth_stats"]["shadow_compare_requests"], 1);
    assert_eq!(payload["auth_stats"]["shadow_compare_mismatches"], 1);
}

#[tokio::test]
async fn proxy_authenticate_preserves_unknown_deny_details_without_code() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move {
            (
                StatusCode::FORBIDDEN,
                Json(json!({"detail": "Completely custom deny"})),
            )
        }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect_err("proxy should preserve deny as error response");

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("deny payload json");
    assert_eq!(payload["detail"], "Completely custom deny");
    assert_eq!(payload.get("code"), None);
}

#[tokio::test]
async fn proxy_authenticate_assigns_code_to_backend_transport_failure() {
    let state = AppState::new(&test_config(
        "http://127.0.0.1:9/_internal/core/auth/authenticate".to_string(),
    ))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect_err("transport failure should be an error response");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("deny payload json");
    assert_eq!(
        payload["detail"],
        "Auth service backend authenticate failed"
    );
    assert_eq!(payload["code"], "backend_authenticate_failed");
}

#[tokio::test]
async fn proxy_authenticate_assigns_code_to_backend_decode_failure() {
    let backend = Router::new().route(
        "/_internal/core/auth/authenticate",
        post(|| async move { (StatusCode::OK, "not-json") }),
    );
    let backend_url = spawn_router(backend).await;
    let state = AppState::new(&test_config(format!(
        "{backend_url}/_internal/core/auth/authenticate"
    )))
    .expect("state");

    let response = proxy_authenticate(
        &state,
        &AuthenticateRequest {
            method: "GET".to_string(),
            path: "/mcp".to_string(),
            query_string: String::new(),
            headers: std::collections::HashMap::new(),
            client_ip: None,
        },
    )
    .await
    .expect_err("decode failure should be an error response");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("read body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("deny payload json");
    assert_eq!(
        payload["detail"],
        "Auth service backend authenticate decode failed"
    );
    assert_eq!(payload["code"], "backend_authenticate_decode_failed");
}

#[tokio::test]
async fn verify_backend_readiness_accepts_healthy_backend() {
    let backend = Router::new().route(
        "/healthz",
        get(|| async move { Json(json!({"status": "ok"})) }),
    );
    let backend_url = spawn_router(backend).await;

    let state = AppState::new(&AuthConfig {
        database_url: None,
        backend_authenticate_url: "http://127.0.0.1:4444/_internal/core/auth/authenticate"
            .to_string(),
        backend_health_url: Some(format!("{backend_url}/healthz")),
        listen_http: "127.0.0.1:8788".to_string(),
        request_timeout_ms: 30_000,
        db_pool_max_size: 8,
        experimental_direct_auth: false,
        shadow_compare_direct_auth: false,
        log_filter: "error".to_string(),
        jwt_secret_key: "this-is-a-long-test-secret-key-32chars".to_string(),
        jwt_algorithm: "HS256".to_string(),
        jwt_audience: "mcpgateway-api".to_string(),
        jwt_issuer: "mcpgateway".to_string(),
        jwt_audience_verification: true,
        jwt_issuer_verification: true,
        require_token_expiration: true,
        require_jti: true,
        require_user_in_db: false,
        platform_admin_email: "admin@example.com".to_string(),
    })
    .expect("state");

    verify_backend_readiness(&state)
        .await
        .expect("healthy backend");
}

#[tokio::test]
async fn verify_backend_readiness_rejects_unhealthy_backend() {
    let backend = Router::new().route(
        "/healthz",
        get(|| async move {
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"status": "down"})),
            )
        }),
    );
    let backend_url = spawn_router(backend).await;

    let state = AppState::new(&AuthConfig {
        database_url: None,
        backend_authenticate_url: "http://127.0.0.1:4444/_internal/core/auth/authenticate"
            .to_string(),
        backend_health_url: Some(format!("{backend_url}/healthz")),
        listen_http: "127.0.0.1:8788".to_string(),
        request_timeout_ms: 30_000,
        db_pool_max_size: 8,
        experimental_direct_auth: false,
        shadow_compare_direct_auth: false,
        log_filter: "error".to_string(),
        jwt_secret_key: "this-is-a-long-test-secret-key-32chars".to_string(),
        jwt_algorithm: "HS256".to_string(),
        jwt_audience: "mcpgateway-api".to_string(),
        jwt_issuer: "mcpgateway".to_string(),
        jwt_audience_verification: true,
        jwt_issuer_verification: true,
        require_token_expiration: true,
        require_jti: true,
        require_user_in_db: false,
        platform_admin_email: "admin@example.com".to_string(),
    })
    .expect("state");

    let err = verify_backend_readiness(&state)
        .await
        .expect_err("unhealthy backend");
    assert!(
        err.to_string().contains("returned 503 Service Unavailable"),
        "unexpected error: {err}"
    );
}
