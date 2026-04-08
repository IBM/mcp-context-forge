// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use crate::config::AuthConfig;
use crate::error::SidecarError;
use async_trait::async_trait;
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use rustls::{
    ClientConfig as RustlsClientConfig, RootCertStore,
    pki_types::{CertificateDer, pem::PemObject},
};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, fs, str::FromStr, sync::Arc};
use tokio_postgres::config::SslMode;
use tokio_postgres_rustls::MakeRustlsConnect;
use tracing::{info, warn};
use url::Url;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionAuthSnapshot {
    pub revoked: bool,
    pub user: Option<UserAuthSnapshot>,
}

#[async_trait]
pub trait SessionAuthSnapshotChecker: Send + Sync {
    async fn lookup_session_auth_snapshot(
        &self,
        jti: &str,
        email: &str,
    ) -> Result<SessionAuthSnapshot, String>;
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
pub struct UserAuthSnapshot {
    pub is_active: bool,
    pub is_admin: bool,
    pub team_ids: Vec<String>,
    pub team_names: HashMap<String, String>,
}

#[async_trait]
pub trait UserAuthSnapshotChecker: Send + Sync {
    async fn lookup_user_auth_snapshot(
        &self,
        email: &str,
    ) -> Result<Option<UserAuthSnapshot>, String>;
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiTokenAuthSnapshot {
    pub token: Option<ApiTokenLookupRecord>,
    pub revoked: bool,
    pub user: Option<UserAuthSnapshot>,
}

#[async_trait]
pub trait ApiTokenAuthSnapshotChecker: Send + Sync {
    async fn lookup_api_token_auth_snapshot(
        &self,
        token: &str,
    ) -> Result<ApiTokenAuthSnapshot, String>;
}

#[derive(Debug, Default)]
pub struct NoopRevocationChecker;

#[async_trait]
impl RevocationChecker for NoopRevocationChecker {
    async fn is_revoked(&self, _jti: &str) -> Result<bool, String> {
        Ok(false)
    }
}

#[derive(Debug, Default)]
pub struct NoopUserLookupChecker;

#[async_trait]
impl UserLookupChecker for NoopUserLookupChecker {
    async fn lookup_user(&self, _email: &str) -> Result<Option<UserLookupRecord>, String> {
        Ok(None)
    }
}

#[derive(Debug, Default)]
pub struct NoopUserAuthSnapshotChecker;

#[async_trait]
impl UserAuthSnapshotChecker for NoopUserAuthSnapshotChecker {
    async fn lookup_user_auth_snapshot(
        &self,
        _email: &str,
    ) -> Result<Option<UserAuthSnapshot>, String> {
        Ok(None)
    }
}

#[derive(Debug, Default)]
pub struct NoopSessionAuthSnapshotChecker;

#[async_trait]
impl SessionAuthSnapshotChecker for NoopSessionAuthSnapshotChecker {
    async fn lookup_session_auth_snapshot(
        &self,
        _jti: &str,
        _email: &str,
    ) -> Result<SessionAuthSnapshot, String> {
        Ok(SessionAuthSnapshot {
            revoked: false,
            user: None,
        })
    }
}

#[derive(Debug, Default)]
pub struct NoopApiTokenLookupChecker;

#[async_trait]
impl ApiTokenLookupChecker for NoopApiTokenLookupChecker {
    async fn lookup_api_token(&self, _token: &str) -> Result<Option<ApiTokenLookupRecord>, String> {
        Ok(None)
    }
}

#[derive(Debug, Default)]
pub struct NoopApiTokenAuthSnapshotChecker;

#[async_trait]
impl ApiTokenAuthSnapshotChecker for NoopApiTokenAuthSnapshotChecker {
    async fn lookup_api_token_auth_snapshot(
        &self,
        _token: &str,
    ) -> Result<ApiTokenAuthSnapshot, String> {
        Ok(ApiTokenAuthSnapshot {
            token: None,
            revoked: false,
            user: None,
        })
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
            .query_opt(
                "SELECT 1 FROM token_revocations WHERE jti = $1 LIMIT 1",
                &[&jti],
            )
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
struct PostgresUserAuthSnapshotChecker {
    pool: Pool,
}

#[async_trait]
impl UserAuthSnapshotChecker for PostgresUserAuthSnapshotChecker {
    async fn lookup_user_auth_snapshot(
        &self,
        email: &str,
    ) -> Result<Option<UserAuthSnapshot>, String> {
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
        let Some(row) = row else {
            return Ok(None);
        };

        let team_rows = client
            .query(
                "SELECT etm.team_id, et.name \
                 FROM email_team_members etm \
                 JOIN email_teams et ON et.id = etm.team_id \
                 WHERE etm.user_email = $1 \
                   AND etm.is_active = TRUE \
                   AND et.is_active = TRUE",
                &[&email],
            )
            .await
            .map_err(|err| format!("failed to query email_team_members: {err}"))?;

        let mut team_ids = Vec::with_capacity(team_rows.len());
        let mut team_names = HashMap::with_capacity(team_rows.len());
        for team_row in team_rows {
            let team_id = team_row.get::<_, String>(0);
            let team_name = team_row.get::<_, String>(1);
            team_ids.push(team_id.clone());
            team_names.insert(team_id, team_name);
        }

        Ok(Some(UserAuthSnapshot {
            is_active: row.get::<_, bool>(0),
            is_admin: row.get::<_, bool>(1),
            team_ids,
            team_names,
        }))
    }
}

#[derive(Clone)]
struct PostgresSessionAuthSnapshotChecker {
    pool: Pool,
}

#[async_trait]
impl SessionAuthSnapshotChecker for PostgresSessionAuthSnapshotChecker {
    async fn lookup_session_auth_snapshot(
        &self,
        jti: &str,
        email: &str,
    ) -> Result<SessionAuthSnapshot, String> {
        let client = self
            .pool
            .get()
            .await
            .map_err(|err| format!("failed to acquire auth DB connection: {err}"))?;
        let row = client
            .query_one(
                "WITH identity_input AS (SELECT $1::text AS jti, $2::text AS email)
                 SELECT
                   EXISTS(SELECT 1 FROM token_revocations tr WHERE tr.jti = identity_input.jti) AS revoked,
                   eu.is_active,
                   eu.is_admin,
                   COALESCE(array_agg(DISTINCT etm.team_id) FILTER (WHERE etm.team_id IS NOT NULL), ARRAY[]::text[]) AS team_ids,
                   COALESCE(array_agg(DISTINCT et.name) FILTER (WHERE et.name IS NOT NULL), ARRAY[]::text[]) AS team_names
                 FROM identity_input
                 LEFT JOIN email_users eu ON eu.email = identity_input.email
                 LEFT JOIN email_team_members etm
                   ON etm.user_email = identity_input.email
                  AND etm.is_active = TRUE
                 LEFT JOIN email_teams et
                   ON et.id = etm.team_id
                  AND et.is_active = TRUE
                 GROUP BY revoked, eu.is_active, eu.is_admin",
                &[&jti, &email],
            )
            .await
            .map_err(|err| format!("failed to query session auth snapshot: {err}"))?;

        let revoked = row.get::<_, bool>(0);
        let is_active = row.get::<_, Option<bool>>(1);
        let is_admin = row.get::<_, Option<bool>>(2);
        let team_ids = row.get::<_, Vec<String>>(3);
        let team_names = row.get::<_, Vec<String>>(4);
        let user = match (is_active, is_admin) {
            (Some(is_active), Some(is_admin)) => Some(UserAuthSnapshot {
                is_active,
                is_admin,
                team_names: team_ids
                    .iter()
                    .cloned()
                    .zip(team_names.into_iter())
                    .collect(),
                team_ids,
            }),
            _ => None,
        };
        Ok(SessionAuthSnapshot { revoked, user })
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
        let expired =
            expires_at.is_some_and(|expires_at| expires_at <= std::time::SystemTime::now());
        Ok(Some(ApiTokenLookupRecord {
            user_email: row.get::<_, String>(0),
            jti: row.get::<_, String>(1),
            team_id: row.get::<_, Option<String>>(2),
            server_id: row.get::<_, Option<String>>(3),
            resource_scopes: row.get::<_, Option<Vec<String>>>(4).unwrap_or_default(),
            expired,
        }))
    }
}

#[derive(Clone)]
struct PostgresApiTokenAuthSnapshotChecker {
    pool: Pool,
}

#[async_trait]
impl ApiTokenAuthSnapshotChecker for PostgresApiTokenAuthSnapshotChecker {
    async fn lookup_api_token_auth_snapshot(
        &self,
        token: &str,
    ) -> Result<ApiTokenAuthSnapshot, String> {
        let token_hash = sha256_hex(token);
        let client = self
            .pool
            .get()
            .await
            .map_err(|err| format!("failed to acquire auth DB connection: {err}"))?;
        let row = client
            .query_opt(
                "WITH token_row AS (
                    SELECT user_email, jti, team_id, server_id, resource_scopes, expires_at
                    FROM email_api_tokens
                    WHERE token_hash = $1 AND is_active = TRUE
                    LIMIT 1
                 )
                 SELECT
                    token_row.user_email,
                    token_row.jti,
                    token_row.team_id,
                    token_row.server_id,
                    COALESCE(token_row.resource_scopes, ARRAY[]::text[]) AS resource_scopes,
                    token_row.expires_at,
                    EXISTS(SELECT 1 FROM token_revocations tr WHERE tr.jti = token_row.jti) AS revoked,
                    eu.is_active,
                    eu.is_admin,
                    COALESCE(array_agg(DISTINCT etm.team_id) FILTER (WHERE etm.team_id IS NOT NULL), ARRAY[]::text[]) AS team_ids,
                    COALESCE(array_agg(DISTINCT et.name) FILTER (WHERE et.name IS NOT NULL), ARRAY[]::text[]) AS team_names
                 FROM token_row
                 LEFT JOIN email_users eu ON eu.email = token_row.user_email
                 LEFT JOIN email_team_members etm
                   ON etm.user_email = token_row.user_email
                  AND etm.is_active = TRUE
                 LEFT JOIN email_teams et
                   ON et.id = etm.team_id
                  AND et.is_active = TRUE
                 GROUP BY
                    token_row.user_email,
                    token_row.jti,
                    token_row.team_id,
                    token_row.server_id,
                    token_row.resource_scopes,
                    token_row.expires_at,
                    revoked,
                    eu.is_active,
                    eu.is_admin",
                &[&token_hash],
            )
            .await
            .map_err(|err| format!("failed to query api token auth snapshot: {err}"))?;

        let Some(row) = row else {
            return Ok(ApiTokenAuthSnapshot {
                token: None,
                revoked: false,
                user: None,
            });
        };
        let expires_at = row.get::<_, Option<std::time::SystemTime>>(5);
        let expired =
            expires_at.is_some_and(|expires_at| expires_at <= std::time::SystemTime::now());
        let token = Some(ApiTokenLookupRecord {
            user_email: row.get::<_, String>(0),
            jti: row.get::<_, String>(1),
            team_id: row.get::<_, Option<String>>(2),
            server_id: row.get::<_, Option<String>>(3),
            resource_scopes: row.get::<_, Vec<String>>(4),
            expired,
        });
        let is_active = row.get::<_, Option<bool>>(7);
        let is_admin = row.get::<_, Option<bool>>(8);
        let team_ids = row.get::<_, Vec<String>>(9);
        let team_names = row.get::<_, Vec<String>>(10);
        let user = match (is_active, is_admin) {
            (Some(is_active), Some(is_admin)) => Some(UserAuthSnapshot {
                is_active,
                is_admin,
                team_names: team_ids
                    .iter()
                    .cloned()
                    .zip(team_names.into_iter())
                    .collect(),
                team_ids,
            }),
            _ => None,
        };
        Ok(ApiTokenAuthSnapshot {
            token,
            revoked: row.get::<_, bool>(6),
            user,
        })
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
#[allow(clippy::struct_field_names)]
struct PostgresTlsOptions {
    ssl_root_cert: Option<String>,
    ssl_cert: Option<String>,
    ssl_key: Option<String>,
}

pub type DirectCheckers = (
    Arc<dyn RevocationChecker>,
    Arc<dyn UserLookupChecker>,
    Arc<dyn UserAuthSnapshotChecker>,
    Arc<dyn ApiTokenLookupChecker>,
    Arc<dyn SessionAuthSnapshotChecker>,
    Arc<dyn ApiTokenAuthSnapshotChecker>,
);

pub fn build_direct_db_checkers(config: &AuthConfig) -> Result<DirectCheckers, SidecarError> {
    let Some(database_url) = config.database_url.as_deref() else {
        return Ok((
            Arc::new(NoopRevocationChecker),
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopUserAuthSnapshotChecker),
            Arc::new(NoopApiTokenLookupChecker),
            Arc::new(NoopSessionAuthSnapshotChecker),
            Arc::new(NoopApiTokenAuthSnapshotChecker),
        ));
    };

    if database_url.starts_with("sqlite:") {
        warn!("Rust auth direct DB revocation checks disabled: sqlite is not supported");
        return Ok((
            Arc::new(NoopRevocationChecker),
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopUserAuthSnapshotChecker),
            Arc::new(NoopApiTokenLookupChecker),
            Arc::new(NoopSessionAuthSnapshotChecker),
            Arc::new(NoopApiTokenAuthSnapshotChecker),
        ));
    }

    let pool = build_postgres_pool(database_url, config.db_pool_max_size)?;
    Ok((
        Arc::new(PostgresRevocationChecker { pool: pool.clone() }),
        Arc::new(PostgresUserLookupChecker { pool: pool.clone() }),
        Arc::new(PostgresUserAuthSnapshotChecker { pool: pool.clone() }),
        Arc::new(PostgresApiTokenLookupChecker { pool: pool.clone() }),
        Arc::new(PostgresSessionAuthSnapshotChecker { pool: pool.clone() }),
        Arc::new(PostgresApiTokenAuthSnapshotChecker { pool }),
    ))
}

fn build_postgres_pool(database_url: &str, db_pool_max_size: usize) -> Result<Pool, SidecarError> {
    let (normalized_url, tls_options) = normalize_postgres_database_url(database_url)?;
    let pg_config = tokio_postgres::Config::from_str(&normalized_url).map_err(|err| {
        SidecarError::Config(format!(
            "invalid CONTEXTFORGE_AUTH_DATABASE_URL '{normalized_url}': {err}"
        ))
    })?;
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
    let mut parsed = Url::parse(&normalized_url).map_err(|err| {
        SidecarError::Config(format!(
            "invalid CONTEXTFORGE_AUTH_DATABASE_URL '{normalized_url}': {err}"
        ))
    })?;
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
    static RUSTLS_CRYPTO_PROVIDER: std::sync::OnceLock<()> = std::sync::OnceLock::new();

    RUSTLS_CRYPTO_PROVIDER.get_or_init(|| {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
}

fn sha256_hex(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
