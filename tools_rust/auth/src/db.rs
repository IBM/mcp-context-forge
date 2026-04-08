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
use std::{fs, str::FromStr, sync::Arc};
use tokio_postgres::config::SslMode;
use tokio_postgres_rustls::MakeRustlsConnect;
use tracing::{info, warn};
use url::Url;

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
pub struct NoopApiTokenLookupChecker;

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
    Arc<dyn ApiTokenLookupChecker>,
);

pub fn build_direct_db_checkers(config: &AuthConfig) -> Result<DirectCheckers, SidecarError> {
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
