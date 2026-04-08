// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Experimental core-owned Rust auth service.

pub mod config;
pub mod core_auth_policy;

use axum::{
    Json, Router,
    extract::State,
    http::{HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use async_trait::async_trait;
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode};
use reqwest::Client;
use rustls::{
    ClientConfig as RustlsClientConfig, RootCertStore,
    pki_types::{CertificateDer, pem::PemObject},
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    str::FromStr,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use thiserror::Error;
use tokio_postgres::config::SslMode;
use tokio_postgres_rustls::MakeRustlsConnect;
use tracing::{error, info, warn};
use url::Url;

const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
const RUNTIME_NAME: &str = "auth";
const INTERNAL_RUNTIME_AUTH_HEADER: &str = "x-contextforge-mcp-runtime-auth";
const INTERNAL_RUNTIME_AUTH_CONTEXT: &str = "contextforge-internal-mcp-runtime-v1";
const DEFAULT_INTERNAL_RUNTIME_AUTH_SECRET: &str = "my-test-salt";

#[derive(Debug, Error)]
pub enum SidecarError {
    #[error("config error: {0}")]
    Config(String),
    #[error("backend readiness check failed: {0}")]
    BackendReadiness(String),
    #[error("http client error: {0}")]
    HttpClient(#[from] reqwest::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JwtVerificationConfig {
    pub secret: String,
    pub algorithm: String,
    pub audience: String,
    pub issuer: String,
    pub verify_audience: bool,
    pub verify_issuer: bool,
    pub require_expiration: bool,
    pub require_jti: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JwtVerifyError {
    MissingRequiredExpiration,
    MissingRequiredJti,
    ExpiredToken,
    InvalidToken,
}

#[derive(Clone)]
pub struct AppState {
    backend_authenticate_url: Arc<str>,
    backend_health_url: Option<Arc<str>>,
    client: Client,
    auth_stats: Arc<AuthStats>,
    jwt_verification: JwtVerificationConfig,
    revocation_checker: Arc<dyn RevocationChecker>,
    user_lookup_checker: Arc<dyn UserLookupChecker>,
    api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
    experimental_direct_auth: bool,
    shadow_compare_direct_auth: bool,
    require_user_in_db: bool,
    platform_admin_email: Arc<str>,
}

#[async_trait]
pub trait RevocationChecker: Send + Sync {
    async fn is_revoked(&self, jti: &str) -> Result<bool, String>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserLookupRecord {
    pub is_active: bool,
    pub is_admin: bool,
}

#[async_trait]
pub trait UserLookupChecker: Send + Sync {
    async fn lookup_user(&self, email: &str) -> Result<Option<UserLookupRecord>, String>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiTokenLookupRecord {
    pub user_email: String,
    pub jti: String,
    pub team_id: Option<String>,
    pub server_id: Option<String>,
    pub resource_scopes: Vec<String>,
    pub expired: bool,
}

#[async_trait]
pub trait ApiTokenLookupChecker: Send + Sync {
    async fn lookup_api_token(&self, token: &str) -> Result<Option<ApiTokenLookupRecord>, String>;
}

#[derive(Debug, Default)]
struct NoopRevocationChecker;

#[async_trait]
impl RevocationChecker for NoopRevocationChecker {
    async fn is_revoked(&self, _jti: &str) -> Result<bool, String> {
        Ok(false)
    }
}

#[derive(Debug, Default)]
struct NoopUserLookupChecker;

#[async_trait]
impl UserLookupChecker for NoopUserLookupChecker {
    async fn lookup_user(&self, _email: &str) -> Result<Option<UserLookupRecord>, String> {
        Ok(None)
    }
}

#[derive(Debug, Default)]
struct NoopApiTokenLookupChecker;

#[async_trait]
impl ApiTokenLookupChecker for NoopApiTokenLookupChecker {
    async fn lookup_api_token(&self, _token: &str) -> Result<Option<ApiTokenLookupRecord>, String> {
        Ok(None)
    }
}

#[derive(Clone)]
struct PostgresRevocationChecker {
    pool: Pool,
}

#[async_trait]
impl RevocationChecker for PostgresRevocationChecker {
    async fn is_revoked(&self, jti: &str) -> Result<bool, String> {
        let client = self
            .pool
            .get()
            .await
            .map_err(|err| format!("failed to acquire auth DB connection: {err}"))?;
        let row = client
            .query_opt("SELECT 1 FROM token_revocations WHERE jti = $1 LIMIT 1", &[&jti])
            .await
            .map_err(|err| format!("failed to query token revocations: {err}"))?;
        Ok(row.is_some())
    }
}

#[derive(Clone)]
struct PostgresUserLookupChecker {
    pool: Pool,
}

#[async_trait]
impl UserLookupChecker for PostgresUserLookupChecker {
    async fn lookup_user(&self, email: &str) -> Result<Option<UserLookupRecord>, String> {
        let client = self
            .pool
            .get()
            .await
            .map_err(|err| format!("failed to acquire auth DB connection: {err}"))?;
        let row = client
            .query_opt(
                "SELECT is_active, is_admin FROM email_users WHERE email = $1 LIMIT 1",
                &[&email],
            )
            .await
            .map_err(|err| format!("failed to query email_users: {err}"))?;
        Ok(row.map(|row| UserLookupRecord {
            is_active: row.get::<_, bool>(0),
            is_admin: row.get::<_, bool>(1),
        }))
    }
}

#[derive(Clone)]
struct PostgresApiTokenLookupChecker {
    pool: Pool,
}

#[async_trait]
impl ApiTokenLookupChecker for PostgresApiTokenLookupChecker {
    async fn lookup_api_token(&self, token: &str) -> Result<Option<ApiTokenLookupRecord>, String> {
        let token_hash = sha256_hex(token);
        let client = self
            .pool
            .get()
            .await
            .map_err(|err| format!("failed to acquire auth DB connection: {err}"))?;
        let row = client
            .query_opt(
                "SELECT user_email, jti, team_id, server_id, resource_scopes, expires_at \
                 FROM email_api_tokens \
                 WHERE token_hash = $1 AND is_active = TRUE \
                 LIMIT 1",
                &[&token_hash],
            )
            .await
            .map_err(|err| format!("failed to query email_api_tokens: {err}"))?;
        let Some(row) = row else {
            return Ok(None);
        };
        let expires_at = row.get::<_, Option<std::time::SystemTime>>(5);
        let expired = expires_at.is_some_and(|expires_at| expires_at <= std::time::SystemTime::now());
        Ok(Some(ApiTokenLookupRecord {
            user_email: row.get::<_, String>(0),
            jti: row.get::<_, String>(1),
            team_id: row.get::<_, Option<String>>(2),
            server_id: row.get::<_, Option<String>>(3),
            resource_scopes: row
                .get::<_, Option<Vec<String>>>(4)
                .unwrap_or_default(),
            expired,
        }))
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
#[allow(clippy::struct_field_names)]
struct PostgresTlsOptions {
    ssl_root_cert: Option<String>,
    ssl_cert: Option<String>,
    ssl_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateRequest {
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub query_string: String,
    #[serde(default)]
    pub headers: std::collections::HashMap<String, String>,
    #[serde(default)]
    pub client_ip: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateResponse {
    pub auth_context: Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub runtime: &'static str,
    pub backend_authenticate_url: String,
    pub backend_health_url: Option<String>,
    pub experimental_direct_auth: bool,
    pub shadow_compare_direct_auth: bool,
    pub auth_stats: AuthStatsSnapshot,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AuthStatsSnapshot {
    pub authenticate_requests: u64,
    pub direct_auth_responses: u64,
    pub proxied_auth_responses: u64,
    pub backend_round_trips: u64,
    pub backend_round_trip_total_ms: u64,
    pub backend_round_trip_max_ms: u64,
    pub backend_failures: u64,
    pub shadow_compare_requests: u64,
    pub shadow_compare_mismatches: u64,
}

#[derive(Debug, Default)]
struct AuthStats {
    authenticate_requests: AtomicU64,
    direct_auth_responses: AtomicU64,
    proxied_auth_responses: AtomicU64,
    backend_round_trips: AtomicU64,
    backend_round_trip_total_ms: AtomicU64,
    backend_round_trip_max_ms: AtomicU64,
    backend_failures: AtomicU64,
    shadow_compare_requests: AtomicU64,
    shadow_compare_mismatches: AtomicU64,
}

impl AppState {
    pub fn new(config: &config::AuthConfig) -> Result<Self, SidecarError> {
        let (revocation_checker, user_lookup_checker, api_token_lookup_checker) =
            build_direct_db_checkers(config)?;
        Self::with_checkers(
            config,
            revocation_checker,
            user_lookup_checker,
            api_token_lookup_checker,
        )
    }

    pub fn with_revocation_checker(
        config: &config::AuthConfig,
        revocation_checker: Arc<dyn RevocationChecker>,
    ) -> Result<Self, SidecarError> {
        Self::with_checkers(
            config,
            revocation_checker,
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopApiTokenLookupChecker),
        )
    }

    pub fn with_checkers(
        config: &config::AuthConfig,
        revocation_checker: Arc<dyn RevocationChecker>,
        user_lookup_checker: Arc<dyn UserLookupChecker>,
        api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
    ) -> Result<Self, SidecarError> {
        let client = Client::builder()
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .build()?;

        Ok(Self {
            backend_authenticate_url: Arc::from(config.backend_authenticate_url.clone()),
            backend_health_url: config.backend_health_url.clone().map(Arc::from),
            client,
            auth_stats: Arc::new(AuthStats::default()),
            jwt_verification: JwtVerificationConfig {
                secret: config.jwt_secret_key.clone(),
                algorithm: config.jwt_algorithm.clone(),
                audience: config.jwt_audience.clone(),
                issuer: config.jwt_issuer.clone(),
                verify_audience: config.jwt_audience_verification,
                verify_issuer: config.jwt_issuer_verification,
                require_expiration: config.require_token_expiration,
                require_jti: config.require_jti,
            },
            revocation_checker,
            user_lookup_checker,
            api_token_lookup_checker,
            experimental_direct_auth: config.experimental_direct_auth,
            shadow_compare_direct_auth: config.shadow_compare_direct_auth,
            require_user_in_db: config.require_user_in_db,
            platform_admin_email: Arc::from(config.platform_admin_email.clone()),
        })
    }

    #[must_use]
    pub fn backend_authenticate_url(&self) -> &str {
        &self.backend_authenticate_url
    }

    #[must_use]
    pub fn backend_health_url(&self) -> Option<&str> {
        self.backend_health_url.as_deref()
    }

    #[must_use]
    fn auth_stats(&self) -> &Arc<AuthStats> {
        &self.auth_stats
    }
}

fn build_direct_db_checkers(
    config: &config::AuthConfig,
) -> Result<
    (
        Arc<dyn RevocationChecker>,
        Arc<dyn UserLookupChecker>,
        Arc<dyn ApiTokenLookupChecker>,
    ),
    SidecarError,
> {
    let Some(database_url) = config.database_url.as_deref() else {
        return Ok((
            Arc::new(NoopRevocationChecker),
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopApiTokenLookupChecker),
        ));
    };

    if database_url.starts_with("sqlite:") {
        warn!("Rust auth direct DB revocation checks disabled: sqlite is not supported");
        return Ok((
            Arc::new(NoopRevocationChecker),
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopApiTokenLookupChecker),
        ));
    }

    let pool = build_postgres_pool(database_url, config.db_pool_max_size)?;
    Ok((
        Arc::new(PostgresRevocationChecker { pool: pool.clone() }),
        Arc::new(PostgresUserLookupChecker { pool: pool.clone() }),
        Arc::new(PostgresApiTokenLookupChecker { pool }),
    ))
}

fn build_postgres_pool(database_url: &str, db_pool_max_size: usize) -> Result<Pool, SidecarError> {
    let (normalized_url, tls_options) = normalize_postgres_database_url(database_url)?;
    let pg_config = tokio_postgres::Config::from_str(&normalized_url)
        .map_err(|err| SidecarError::Config(format!("invalid CONTEXTFORGE_AUTH_DATABASE_URL '{normalized_url}': {err}")))?;
    let tls_connector = build_postgres_tls_connector(&tls_options)?;
    let mgr_config = ManagerConfig {
        recycling_method: RecyclingMethod::Fast,
    };
    match pg_config.get_ssl_mode() {
        SslMode::Disable => info!("Rust auth DB pool TLS disabled via sslmode=disable"),
        SslMode::Prefer => info!("Rust auth DB pool TLS optional via sslmode=prefer"),
        SslMode::Require => info!("Rust auth DB pool TLS required via sslmode=require"),
        _ => info!("Rust auth DB pool TLS configured with a non-default sslmode"),
    }
    let manager = Manager::from_config(pg_config, tls_connector, mgr_config);
    Pool::builder(manager)
        .max_size(db_pool_max_size)
        .build()
        .map_err(|err| SidecarError::Config(format!("failed to build Rust auth DB pool: {err}")))
}

fn normalize_postgres_database_url(
    database_url: &str,
) -> Result<(String, PostgresTlsOptions), SidecarError> {
    let normalized_url = database_url.replace("postgresql+psycopg://", "postgresql://");
    let mut parsed = Url::parse(&normalized_url)
        .map_err(|err| SidecarError::Config(format!("invalid CONTEXTFORGE_AUTH_DATABASE_URL '{normalized_url}': {err}")))?;
    let mut tls_options = PostgresTlsOptions::default();
    let retained_query_pairs = parsed
        .query_pairs()
        .into_owned()
        .filter_map(|(key, value)| match key.as_str() {
            "sslrootcert" => {
                tls_options.ssl_root_cert = Some(value);
                None
            }
            "sslcert" => {
                tls_options.ssl_cert = Some(value);
                None
            }
            "sslkey" => {
                tls_options.ssl_key = Some(value);
                None
            }
            _ => Some((key, value)),
        })
        .collect::<Vec<_>>();
    {
        let mut query_pairs = parsed.query_pairs_mut();
        query_pairs.clear();
        query_pairs.extend_pairs(
            retained_query_pairs
                .iter()
                .map(|(key, value)| (key.as_str(), value.as_str())),
        );
    }

    Ok((parsed.to_string(), tls_options))
}

fn build_postgres_tls_connector(
    tls_options: &PostgresTlsOptions,
) -> Result<MakeRustlsConnect, SidecarError> {
    if tls_options.ssl_cert.is_some() || tls_options.ssl_key.is_some() {
        return Err(SidecarError::Config(
            "CONTEXTFORGE_AUTH_DATABASE_URL client certificate authentication via sslcert/sslkey is not supported yet"
                .to_string(),
        ));
    }

    ensure_rustls_crypto_provider();

    let mut root_cert_store = RootCertStore::empty();
    let native_certs = rustls_native_certs::load_native_certs();
    for load_error in native_certs.errors {
        warn!("Rust auth DB TLS native root load warning: {load_error}");
    }
    let (_added, _ignored) = root_cert_store.add_parsable_certificates(native_certs.certs);

    if let Some(path) = tls_options.ssl_root_cert.as_deref() {
        let certificates = load_pem_certificates(path)?;
        let (added, _ignored) = root_cert_store.add_parsable_certificates(certificates);
        if added == 0 {
            return Err(SidecarError::Config(format!(
                "invalid CONTEXTFORGE_AUTH_DATABASE_URL sslrootcert '{path}': no certificates were parsed"
            )));
        }
    }

    let tls_connector = RustlsClientConfig::builder()
        .with_root_certificates(root_cert_store)
        .with_no_client_auth();

    Ok(MakeRustlsConnect::new(tls_connector))
}

fn load_pem_certificates(path: &str) -> Result<Vec<CertificateDer<'static>>, SidecarError> {
    let pem_bytes = fs::read(path).map_err(|err| {
        SidecarError::Config(format!(
            "invalid CONTEXTFORGE_AUTH_DATABASE_URL sslrootcert '{path}': {err}"
        ))
    })?;
    let certificates = CertificateDer::pem_slice_iter(&pem_bytes)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| {
            SidecarError::Config(format!(
                "invalid CONTEXTFORGE_AUTH_DATABASE_URL sslrootcert '{path}': {err}"
            ))
        })?;
    if certificates.is_empty() {
        return Err(SidecarError::Config(format!(
            "invalid CONTEXTFORGE_AUTH_DATABASE_URL sslrootcert '{path}': no certificates were parsed"
        )));
    }
    Ok(certificates)
}

fn ensure_rustls_crypto_provider() {
    static RUSTLS_CRYPTO_PROVIDER: OnceLock<()> = OnceLock::new();

    RUSTLS_CRYPTO_PROVIDER.get_or_init(|| {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(health))
        .route("/_internal/core/auth/authenticate", post(authenticate))
        .with_state(state)
}

pub async fn run(config: config::AuthConfig) -> Result<(), SidecarError> {
    let state = AppState::new(&config)?;
    verify_backend_readiness(&state).await?;
    let listener = tokio::net::TcpListener::bind(config.listen_addr().map_err(SidecarError::Config)?).await?;
    axum::serve(listener, build_router(state)).await?;
    Ok(())
}

async fn verify_backend_readiness(state: &AppState) -> Result<(), SidecarError> {
    let Some(health_url) = state.backend_health_url() else {
        return Ok(());
    };

    let response = state.client.get(health_url).send().await.map_err(|err| {
        SidecarError::BackendReadiness(format!("GET {health_url} failed: {err}"))
    })?;

    if !response.status().is_success() {
        return Err(SidecarError::BackendReadiness(format!(
            "GET {health_url} returned {}",
            response.status()
        )));
    }

    Ok(())
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        runtime: "contextforge-auth",
        backend_authenticate_url: state.backend_authenticate_url().to_string(),
        backend_health_url: state.backend_health_url().map(str::to_string),
        experimental_direct_auth: state.experimental_direct_auth,
        shadow_compare_direct_auth: state.shadow_compare_direct_auth,
        auth_stats: state.auth_stats().snapshot(),
    })
}

async fn authenticate(State(state): State<AppState>, Json(request): Json<AuthenticateRequest>) -> Response {
    match proxy_authenticate(&state, &request).await {
        Ok(response) => Json(response).into_response(),
        Err(response) => response,
    }
}

pub fn verify_jwt_token(token: &str, config: &JwtVerificationConfig) -> Result<Value, JwtVerifyError> {
    let algorithm = match config.algorithm.as_str() {
        "HS256" => Algorithm::HS256,
        _ => return Err(JwtVerifyError::InvalidToken),
    };

    let mut validation = Validation::new(algorithm);
    validation.validate_aud = config.verify_audience;
    validation.validate_exp = config.require_expiration;
    validation.validate_nbf = false;

    if config.require_expiration {
        validation.required_spec_claims.insert("exp".to_string());
    } else {
        validation.required_spec_claims.remove("exp");
    }

    if config.verify_audience {
        validation.set_audience(&[config.audience.as_str()]);
    }

    if config.verify_issuer {
        validation.set_issuer(&[config.issuer.as_str()]);
    }

    let payload = decode::<Value>(
        token,
        &DecodingKey::from_secret(config.secret.as_bytes()),
        &validation,
    )
    .map(|data| data.claims)
    .map_err(|err| match err.kind() {
        jsonwebtoken::errors::ErrorKind::ExpiredSignature => JwtVerifyError::ExpiredToken,
        jsonwebtoken::errors::ErrorKind::MissingRequiredClaim(claim) if claim == "exp" => {
            JwtVerifyError::MissingRequiredExpiration
        }
        _ => JwtVerifyError::InvalidToken,
    })?;

    if config.require_jti && !payload.as_object().is_some_and(|payload| payload.contains_key("jti")) {
        return Err(JwtVerifyError::MissingRequiredJti);
    }

    Ok(payload)
}

#[allow(clippy::result_large_err)]
async fn proxy_authenticate(state: &AppState, request: &AuthenticateRequest) -> Result<AuthenticateResponse, Response> {
    state.auth_stats().record_authenticate_request();
    if has_empty_bearer_credentials(&request.headers) {
        return Err(unauthorized_bearer_response("Invalid authentication credentials"));
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
                        Ok(true) => return Err(unauthorized_bearer_response_with_code("Token has been revoked", "token_revoked")),
                        Ok(false) => {}
                        Err(err) => {
                            warn!("auth service token revocation check failed for jti={jti}: {err}");
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
                    return Err(unauthorized_bearer_response("Invalid authentication credentials"));
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
                    .map_err(|_| unauthorized_bearer_response("Invalid authentication credentials"))?
                else {
                    return Err(unauthorized_bearer_response("Invalid authentication credentials"));
                };

                if api_token.expired {
                    return Err(unauthorized_bearer_response_with_code(
                        "API token expired",
                        "invalid_credentials",
                    ));
                }

                match state.revocation_checker.is_revoked(&api_token.jti).await {
                    Ok(true) => {
                        return Err(unauthorized_bearer_response_with_code(
                            "API token has been revoked",
                            "invalid_credentials",
                        ));
                    }
                    Ok(false) => {}
                    Err(_) => return Err(unauthorized_bearer_response("Invalid authentication credentials")),
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
    state.auth_stats().record_proxied_auth_response();
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
                .auth_stats()
                .record_backend_round_trip(backend_round_trip_started.elapsed(), true);
            error!("auth service backend authenticate failed: {err}");
            json_response_with_code(
                StatusCode::BAD_GATEWAY,
                "backend_authenticate_failed",
                json!({"detail": "Auth service backend authenticate failed"}),
            )
        })?;
    state
        .auth_stats()
        .record_backend_round_trip(backend_round_trip_started.elapsed(), false);

    let status = backend_response.status();
    if !status.is_success() {
        let body = backend_response
            .bytes()
            .await
            .unwrap_or_else(|_| axum::body::Bytes::from_static(br#"{"detail":"Auth service backend authenticate failed"}"#));
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
    state.auth_stats().record_direct_auth_response();
    if !state.shadow_compare_direct_auth {
        return;
    }
    let mismatch = match proxy_backend_once(state, request).await {
        Ok(backend_response) => normalize_auth_context(backend_response.auth_context)
            .map(|auth_context| auth_context != response.auth_context)
            .unwrap_or(true),
        Err(_) => true,
    };
    state.auth_stats().record_shadow_compare(mismatch);
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
                .auth_stats()
                .record_backend_round_trip(backend_round_trip_started.elapsed(), true);
            error!("auth service backend authenticate failed: {err}");
            json_response_with_code(
                StatusCode::BAD_GATEWAY,
                "backend_authenticate_failed",
                json!({"detail": "Auth service backend authenticate failed"}),
            )
        })?;
    state
        .auth_stats()
        .record_backend_round_trip(backend_round_trip_started.elapsed(), false);

    let status = backend_response.status();
    if !status.is_success() {
        let body = backend_response
            .bytes()
            .await
            .unwrap_or_else(|_| axum::body::Bytes::from_static(br#"{"detail":"Auth service backend authenticate failed"}"#));
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

fn normalize_deny_response_body(body: axum::body::Bytes) -> axum::body::Bytes {
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
        return axum::body::Bytes::from(
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
        _ => None,
    }
}

fn has_empty_bearer_credentials(headers: &std::collections::HashMap<String, String>) -> bool {
    bearer_token_state(headers).is_some_and(|token| token.is_empty())
}

fn bearer_token(headers: &std::collections::HashMap<String, String>) -> Option<&str> {
    bearer_token_state(headers).filter(|token| !token.is_empty())
}

fn bearer_token_state<'a>(headers: &'a std::collections::HashMap<String, String>) -> Option<&'a str> {
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
    let mut response = json_response_with_code(
        StatusCode::UNAUTHORIZED,
        code,
        json!({ "detail": detail }),
    );
    response.headers_mut().insert(
        axum::http::header::WWW_AUTHENTICATE,
        HeaderValue::from_static("Bearer"),
    );
    response
}

fn sha256_hex(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

#[allow(clippy::result_large_err)]
fn normalize_auth_context(auth_context: Value) -> Result<Value, Response> {
    let Value::Object(mut auth_context) = auth_context else {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    };

    if let Some(teams) = auth_context.get("teams").cloned() {
        match teams {
            Value::Null => {
                if !auth_context
                    .get("is_admin")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                {
                    auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
                }
            }
            Value::Array(raw_teams) => {
                let normalized_payload = Value::Object(
                    [("teams".to_string(), Value::Array(raw_teams))]
                        .into_iter()
                        .collect::<Map<String, Value>>(),
                );
                let normalized_teams = core_auth_policy::normalize_token_teams(&normalized_payload).unwrap_or_default();
                auth_context.insert(
                    "teams".to_string(),
                    Value::Array(normalized_teams.into_iter().map(Value::String).collect()),
                );
            }
            _ => {
                return Err(json_response_with_code(
                    StatusCode::BAD_GATEWAY,
                    "invalid_auth_context",
                    json!({"detail": "Auth service received invalid auth context"}),
                ));
            }
        }
    } else if !auth_context
        .get("is_admin")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
    }

    let token_use = auth_context
        .get("token_use")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let email = auth_context.get("email").and_then(Value::as_str);
    let is_authenticated = auth_context
        .get("is_authenticated")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if token_use != "session" && is_authenticated && email.is_none_or(str::is_empty) {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    }
    if is_authenticated
        && let Some(token_payload) = auth_context
            .get("policy_inputs")
            .and_then(Value::as_object)
            .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        && let Some(token_email) = token_payload
            .as_object()
            .and_then(|payload| payload.get("sub").and_then(Value::as_str).or_else(|| payload.get("email").and_then(Value::as_str)))
        && email != Some(token_email)
    {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    }
    if token_use != "session" {
        if let Some(policy_payload) = auth_context
            .get("policy_inputs")
            .and_then(Value::as_object)
            .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        {
            let normalized_teams = core_auth_policy::normalize_token_teams(policy_payload);
            auth_context.insert(
                "teams".to_string(),
                match normalized_teams {
                    None => Value::Null,
                    Some(teams) => Value::Array(teams.into_iter().map(Value::String).collect()),
                },
            );
        }
    } else if let Some(policy_inputs) = auth_context
        .get("policy_inputs")
        .and_then(Value::as_object)
    {
        let session_email = auth_context.get("email").and_then(Value::as_str);
        if session_email.is_none_or(str::is_empty) {
            auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
        } else if policy_inputs
            .get("db_user_is_admin")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            auth_context.insert("teams".to_string(), Value::Null);
        } else if let Some(policy_payload) = policy_inputs.get("token_payload") {
            let db_teams = match policy_inputs.get("db_teams") {
                Some(Value::Null) => {
                    return Err(json_response_with_code(
                        StatusCode::BAD_GATEWAY,
                        "invalid_auth_context",
                        json!({"detail": "Auth service received invalid auth context"}),
                    ));
                }
                Some(Value::Array(db_teams)) => Some(
                    db_teams
                        .iter()
                        .filter_map(Value::as_str)
                        .map(std::string::ToString::to_string)
                        .collect::<Vec<_>>(),
                ),
                _ => {
                    return Err(json_response_with_code(
                        StatusCode::BAD_GATEWAY,
                        "invalid_auth_context",
                        json!({"detail": "Auth service received invalid auth context"}),
                    ));
                }
            };

            let resolved_teams = core_auth_policy::resolve_session_teams(
                policy_payload,
                session_email,
                db_teams.as_deref(),
            );
            auth_context.insert(
                "teams".to_string(),
                match resolved_teams {
                    None => Value::Null,
                    Some(teams) => Value::Array(teams.into_iter().map(Value::String).collect()),
                },
            );
        }
    }

    let token_use = auth_context
        .get("token_use")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let team_id = auth_context
        .get("teams")
        .and_then(primary_team_id)
        .filter(|_| token_use != "session");
    if let Some(team_id) = team_id {
        auth_context.insert("team_id".to_string(), Value::String(team_id));
    } else if auth_context.contains_key("team_id") {
        auth_context.insert("team_id".to_string(), Value::Null);
    }

    let normalized_teams = auth_context.get("teams");
    let primary_team_id = normalized_teams.and_then(primary_team_id);
    let team_name = derive_team_name(
        auth_context
            .get("policy_inputs")
            .and_then(Value::as_object),
        &token_use,
        primary_team_id.as_deref(),
    );
    if let Some(team_name) = team_name {
        auth_context.insert("team_name".to_string(), Value::String(team_name));
    } else if auth_context.contains_key("team_name") && primary_team_id.is_none() {
        auth_context.insert("team_name".to_string(), Value::Null);
    }

    let token_payload = auth_context
        .get("policy_inputs")
        .and_then(Value::as_object)
        .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        .cloned();

    let scoped_permissions = derive_scoped_permissions(token_payload.as_ref());
    if let Some(scoped_permissions) = scoped_permissions {
        auth_context.insert(
            "scoped_permissions".to_string(),
            Value::Array(scoped_permissions.into_iter().map(Value::String).collect()),
        );
    }

    let scoped_server_id = derive_scoped_server_id(token_payload.as_ref());
    if let Some(scoped_server_id) = scoped_server_id {
        auth_context.insert(
            "scoped_server_id".to_string(),
            Value::String(scoped_server_id),
        );
    }

    let permission_is_admin = derive_permission_is_admin(
        auth_context
            .get("policy_inputs")
            .and_then(Value::as_object),
        auth_context
            .get("is_admin")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    auth_context.insert(
        "permission_is_admin".to_string(),
        Value::Bool(permission_is_admin),
    );

    if has_token_payload(
        auth_context
            .get("policy_inputs")
            .and_then(Value::as_object),
    ) {
        auth_context.insert("auth_method".to_string(), Value::String("jwt".to_string()));
    }

    Ok(Value::Object(auth_context))
}

fn primary_team_id(teams: &Value) -> Option<String> {
    match teams {
        Value::Array(team_values) if team_values.len() == 1 => {
            team_values.first().and_then(Value::as_str).map(str::to_string)
        }
        _ => None,
    }
}

fn derive_team_name(
    policy_inputs: Option<&Map<String, Value>>,
    token_use: &str,
    primary_team_id: Option<&str>,
) -> Option<String> {
    let primary_team_id = primary_team_id?;
    let policy_inputs = policy_inputs?;

    if let Some(team_name) = policy_inputs
        .get("team_names")
        .and_then(Value::as_object)
        .and_then(|team_names| team_names.get(primary_team_id))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|team_name| !team_name.is_empty())
    {
        return Some(team_name.to_string());
    }

    if token_use == "session" {
        return None;
    }

    let token_payload = policy_inputs.get("token_payload")?.as_object()?;
    let raw_teams = token_payload.get("teams")?.as_array()?;
    for raw_team in raw_teams {
        match raw_team {
            Value::Object(raw_team)
                if raw_team.get("id").and_then(Value::as_str) == Some(primary_team_id) =>
            {
                if let Some(team_name) = raw_team
                    .get("name")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|team_name| !team_name.is_empty())
                {
                    return Some(team_name.to_string());
                }
            }
            Value::String(raw_team_id) if raw_team_id == primary_team_id => return None,
            _ => {}
        }
    }

    None
}

fn derive_scoped_permissions(token_payload: Option<&Value>) -> Option<Vec<String>> {
    let token_payload = token_payload?.as_object()?;
    let scopes = token_payload.get("scopes")?.as_object()?;
    let permissions = scopes.get("permissions")?.as_array()?;
    Some(
        permissions
            .iter()
            .filter_map(Value::as_str)
            .map(str::trim)
            .filter(|permission| !permission.is_empty())
            .map(str::to_string)
            .collect(),
    )
}

fn derive_scoped_server_id(token_payload: Option<&Value>) -> Option<String> {
    token_payload
        .and_then(Value::as_object)
        .and_then(|token_payload| token_payload.get("scopes"))
        .and_then(Value::as_object)
        .and_then(|scopes| scopes.get("server_id"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|server_id| !server_id.is_empty())
        .map(str::to_string)
}

fn derive_permission_is_admin(policy_inputs: Option<&Map<String, Value>>, is_admin: bool) -> bool {
    let db_user_is_admin = policy_inputs
        .and_then(|policy_inputs| policy_inputs.get("db_user_is_admin"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    db_user_is_admin || is_admin
}

fn has_token_payload(policy_inputs: Option<&Map<String, Value>>) -> bool {
    policy_inputs
        .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        .is_some()
}

impl AuthStats {
    fn snapshot(&self) -> AuthStatsSnapshot {
        AuthStatsSnapshot {
            authenticate_requests: self.authenticate_requests.load(Ordering::Relaxed),
            direct_auth_responses: self.direct_auth_responses.load(Ordering::Relaxed),
            proxied_auth_responses: self.proxied_auth_responses.load(Ordering::Relaxed),
            backend_round_trips: self.backend_round_trips.load(Ordering::Relaxed),
            backend_round_trip_total_ms: self.backend_round_trip_total_ms.load(Ordering::Relaxed),
            backend_round_trip_max_ms: self.backend_round_trip_max_ms.load(Ordering::Relaxed),
            backend_failures: self.backend_failures.load(Ordering::Relaxed),
            shadow_compare_requests: self.shadow_compare_requests.load(Ordering::Relaxed),
            shadow_compare_mismatches: self.shadow_compare_mismatches.load(Ordering::Relaxed),
        }
    }

    fn record_authenticate_request(&self) {
        self.authenticate_requests.fetch_add(1, Ordering::Relaxed);
    }

    fn record_backend_round_trip(&self, elapsed: Duration, failed: bool) {
        self.backend_round_trips.fetch_add(1, Ordering::Relaxed);
        let elapsed_ms = elapsed.as_millis().min(u128::from(u64::MAX)) as u64;
        self.backend_round_trip_total_ms
            .fetch_add(elapsed_ms, Ordering::Relaxed);
        update_max_counter(&self.backend_round_trip_max_ms, elapsed_ms);
        if failed {
            self.backend_failures.fetch_add(1, Ordering::Relaxed);
        }
    }

    fn record_direct_auth_response(&self) {
        self.direct_auth_responses.fetch_add(1, Ordering::Relaxed);
    }

    fn record_proxied_auth_response(&self) {
        self.proxied_auth_responses.fetch_add(1, Ordering::Relaxed);
    }

    fn record_shadow_compare(&self, mismatch: bool) {
        self.shadow_compare_requests.fetch_add(1, Ordering::Relaxed);
        if mismatch {
            self.shadow_compare_mismatches.fetch_add(1, Ordering::Relaxed);
        }
    }
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    (status, Json(payload)).into_response()
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

fn update_max_counter(counter: &AtomicU64, candidate: u64) {
    let mut current = counter.load(Ordering::Relaxed);
    while candidate > current {
        match counter.compare_exchange_weak(
            current,
            candidate,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
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
    let secret =
        std::env::var("AUTH_ENCRYPTION_SECRET").unwrap_or_else(|_| DEFAULT_INTERNAL_RUNTIME_AUTH_SECRET.to_string());
    let digest = Sha256::digest(format!("{secret}:{INTERNAL_RUNTIME_AUTH_CONTEXT}").as_bytes());
    HeaderValue::from_str(&hex_encode(digest.as_ref()))
        .expect("derived internal auth header must be valid")
}

#[cfg(test)]
mod tests {
    use super::{
        ApiTokenLookupChecker, ApiTokenLookupRecord, AppState, AuthenticateRequest,
        INTERNAL_RUNTIME_AUTH_HEADER, RUNTIME_HEADER, RUNTIME_NAME, RevocationChecker,
        UserLookupChecker, UserLookupRecord, build_router, normalize_auth_context,
        proxy_authenticate, verify_backend_readiness, verify_jwt_token,
        JwtVerificationConfig, JwtVerifyError,
    };
    use crate::config::AuthConfig;
    use async_trait::async_trait;
    use axum::{Json, Router, http::{HeaderMap, StatusCode}, routing::{get, post}};
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
            response.headers().get("www-authenticate").and_then(|v| v.to_str().ok()),
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
        assert_eq!(payload["detail"], "Auth service received invalid auth context");
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
        assert_eq!(payload["detail"], "Auth service received invalid auth context");
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
        assert_eq!(payload["detail"], "Auth service received invalid auth context");
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
        assert_eq!(payload["detail"], "Auth service received invalid auth context");
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
        assert_eq!(payload["detail"], "Auth service received invalid auth context");
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
        let state = AppState::new(&test_config(format!("{backend_url}/_internal/core/auth/authenticate"))).expect("state");

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
        let state = AppState::new(&test_config(format!("{backend_url}/_internal/core/auth/authenticate"))).expect("state");

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
        assert!(payload["auth_stats"]["backend_round_trip_total_ms"].as_u64().unwrap_or(0) >= 15);
        assert!(payload["auth_stats"]["backend_round_trip_max_ms"].as_u64().unwrap_or(0) >= 15);
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
        let state = AppState::new(&test_config(format!("{backend_url}/_internal/core/auth/authenticate"))).expect("state");

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
        let payload: serde_json::Value =
            serde_json::from_slice(&body).expect("deny payload json");
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
            response.headers().get("www-authenticate").and_then(|v| v.to_str().ok()),
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
                headers: [("authorization".to_string(), "Bearer definitely-not-a-jwt".to_string())]
                    .into_iter()
                    .collect(),
                client_ip: None,
            },
        )
        .await
        .expect_err("invalid bearer jwt should fail closed");

        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(
            response.headers().get("www-authenticate").and_then(|v| v.to_str().ok()),
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
            response.headers().get("www-authenticate").and_then(|v| v.to_str().ok()),
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
            response.headers().get("www-authenticate").and_then(|v| v.to_str().ok()),
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
    async fn proxy_authenticate_rejects_missing_user_when_require_user_in_db_is_enabled_without_backend_call() {
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
    async fn proxy_authenticate_returns_direct_platform_admin_bootstrap_auth_context_without_backend_call() {
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
                headers: [("authorization".to_string(), "Bearer opaque-api-token".to_string())]
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
        let state = AppState::new(&test_config(format!("{backend_url}/_internal/core/auth/authenticate"))).expect("state");

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
        let payload: serde_json::Value =
            serde_json::from_slice(&body).expect("deny payload json");
        assert_eq!(payload["detail"], "Completely custom deny");
        assert_eq!(payload.get("code"), None);
    }

    #[tokio::test]
    async fn proxy_authenticate_assigns_code_to_backend_transport_failure() {
        let state = AppState::new(&test_config("http://127.0.0.1:9/_internal/core/auth/authenticate".to_string()))
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
        let payload: serde_json::Value =
            serde_json::from_slice(&body).expect("deny payload json");
        assert_eq!(payload["detail"], "Auth service backend authenticate failed");
        assert_eq!(payload["code"], "backend_authenticate_failed");
    }

    #[tokio::test]
    async fn proxy_authenticate_assigns_code_to_backend_decode_failure() {
        let backend = Router::new().route(
            "/_internal/core/auth/authenticate",
            post(|| async move { (StatusCode::OK, "not-json") }),
        );
        let backend_url = spawn_router(backend).await;
        let state = AppState::new(&test_config(format!("{backend_url}/_internal/core/auth/authenticate"))).expect("state");

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
        let payload: serde_json::Value =
            serde_json::from_slice(&body).expect("deny payload json");
        assert_eq!(payload["detail"], "Auth service backend authenticate decode failed");
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
            backend_authenticate_url: "http://127.0.0.1:4444/_internal/core/auth/authenticate".to_string(),
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
            backend_authenticate_url: "http://127.0.0.1:4444/_internal/core/auth/authenticate".to_string(),
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
}
