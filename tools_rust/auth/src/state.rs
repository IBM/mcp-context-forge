// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use crate::{
    config,
    db::{
        ApiTokenAuthSnapshotChecker, ApiTokenLookupChecker, NoopApiTokenAuthSnapshotChecker,
        NoopApiTokenLookupChecker, NoopSessionAuthSnapshotChecker, NoopUserAuthSnapshotChecker,
        NoopUserLookupChecker, RevocationChecker, SessionAuthSnapshotChecker, UserAuthSnapshot,
        UserAuthSnapshotChecker, UserLookupChecker, build_direct_db_checkers,
    },
    error::SidecarError,
    jwt::JwtVerificationConfig,
    stats::AuthStats,
};
use reqwest::Client;
use std::{
    collections::HashMap,
    sync::{Arc, RwLock},
    time::{Duration, Instant},
};

use crate::db::{ApiTokenAuthSnapshot, ApiTokenLookupRecord, SessionAuthSnapshot};

const REVOCATION_CACHE_TTL: Duration = Duration::from_secs(30);
const USER_SNAPSHOT_CACHE_TTL: Duration = Duration::from_secs(60);
const API_TOKEN_CACHE_TTL: Duration = Duration::from_secs(60);
const SESSION_AUTH_SNAPSHOT_CACHE_TTL: Duration = Duration::from_secs(60);
const API_TOKEN_AUTH_SNAPSHOT_CACHE_TTL: Duration = Duration::from_secs(60);

#[derive(Clone)]
pub struct CacheEntry<T> {
    pub expires_at: Instant,
    pub value: T,
}

#[derive(Clone)]
pub struct AppState {
    pub backend_authenticate_url: Arc<str>,
    pub backend_health_url: Option<Arc<str>>,
    pub client: Client,
    pub auth_stats: Arc<AuthStats>,
    pub jwt_verification: JwtVerificationConfig,
    pub revocation_checker: Arc<dyn RevocationChecker>,
    pub user_lookup_checker: Arc<dyn UserLookupChecker>,
    pub user_auth_snapshot_checker: Arc<dyn UserAuthSnapshotChecker>,
    pub api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
    pub session_auth_snapshot_checker: Arc<dyn SessionAuthSnapshotChecker>,
    pub api_token_auth_snapshot_checker: Arc<dyn ApiTokenAuthSnapshotChecker>,
    pub experimental_direct_auth: bool,
    pub shadow_compare_direct_auth: bool,
    pub benchmark_allow_immediate: bool,
    pub require_user_in_db: bool,
    pub platform_admin_email: Arc<str>,
    pub revocation_cache_ttl: Duration,
    pub user_snapshot_cache_ttl: Duration,
    pub api_token_cache_ttl: Duration,
    pub session_auth_snapshot_cache_ttl: Duration,
    pub api_token_auth_snapshot_cache_ttl: Duration,
    pub revocation_cache: Arc<RwLock<HashMap<String, CacheEntry<bool>>>>,
    pub user_snapshot_cache: Arc<RwLock<HashMap<String, CacheEntry<Option<UserAuthSnapshot>>>>>,
    pub api_token_cache: Arc<RwLock<HashMap<String, CacheEntry<Option<ApiTokenLookupRecord>>>>>,
    pub session_auth_snapshot_cache: Arc<RwLock<HashMap<String, CacheEntry<SessionAuthSnapshot>>>>,
    pub api_token_auth_snapshot_cache:
        Arc<RwLock<HashMap<String, CacheEntry<ApiTokenAuthSnapshot>>>>,
}

impl AppState {
    pub fn new(config: &config::AuthConfig) -> Result<Self, SidecarError> {
        let (
            revocation_checker,
            user_lookup_checker,
            user_auth_snapshot_checker,
            api_token_lookup_checker,
            session_auth_snapshot_checker,
            api_token_auth_snapshot_checker,
        ) = build_direct_db_checkers(config)?;
        Self::with_snapshot_checkers(
            config,
            revocation_checker,
            user_lookup_checker,
            user_auth_snapshot_checker,
            api_token_lookup_checker,
            session_auth_snapshot_checker,
            api_token_auth_snapshot_checker,
        )
    }

    pub fn with_revocation_checker(
        config: &config::AuthConfig,
        revocation_checker: Arc<dyn RevocationChecker>,
    ) -> Result<Self, SidecarError> {
        Self::with_snapshot_checkers(
            config,
            revocation_checker,
            Arc::new(NoopUserLookupChecker),
            Arc::new(NoopUserAuthSnapshotChecker),
            Arc::new(NoopApiTokenLookupChecker),
            Arc::new(NoopSessionAuthSnapshotChecker),
            Arc::new(NoopApiTokenAuthSnapshotChecker),
        )
    }

    pub fn with_checkers(
        config: &config::AuthConfig,
        revocation_checker: Arc<dyn RevocationChecker>,
        user_lookup_checker: Arc<dyn UserLookupChecker>,
        user_auth_snapshot_checker: Arc<dyn UserAuthSnapshotChecker>,
        api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
    ) -> Result<Self, SidecarError> {
        let session_auth_snapshot_checker: Arc<dyn SessionAuthSnapshotChecker> =
            Arc::new(CompatSessionAuthSnapshotChecker {
                revocation_checker: revocation_checker.clone(),
                user_auth_snapshot_checker: user_auth_snapshot_checker.clone(),
            });
        let api_token_auth_snapshot_checker: Arc<dyn ApiTokenAuthSnapshotChecker> =
            Arc::new(CompatApiTokenAuthSnapshotChecker {
                revocation_checker: revocation_checker.clone(),
                user_auth_snapshot_checker: user_auth_snapshot_checker.clone(),
                api_token_lookup_checker: api_token_lookup_checker.clone(),
            });
        Self::with_snapshot_checkers(
            config,
            revocation_checker,
            user_lookup_checker,
            user_auth_snapshot_checker,
            api_token_lookup_checker,
            session_auth_snapshot_checker,
            api_token_auth_snapshot_checker,
        )
    }

    pub fn with_snapshot_checkers(
        config: &config::AuthConfig,
        revocation_checker: Arc<dyn RevocationChecker>,
        user_lookup_checker: Arc<dyn UserLookupChecker>,
        user_auth_snapshot_checker: Arc<dyn UserAuthSnapshotChecker>,
        api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
        session_auth_snapshot_checker: Arc<dyn SessionAuthSnapshotChecker>,
        api_token_auth_snapshot_checker: Arc<dyn ApiTokenAuthSnapshotChecker>,
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
            user_auth_snapshot_checker,
            api_token_lookup_checker,
            session_auth_snapshot_checker,
            api_token_auth_snapshot_checker,
            experimental_direct_auth: config.experimental_direct_auth,
            shadow_compare_direct_auth: config.shadow_compare_direct_auth,
            benchmark_allow_immediate: config.benchmark_allow_immediate,
            require_user_in_db: config.require_user_in_db,
            platform_admin_email: Arc::from(config.platform_admin_email.clone()),
            revocation_cache_ttl: REVOCATION_CACHE_TTL,
            user_snapshot_cache_ttl: USER_SNAPSHOT_CACHE_TTL,
            api_token_cache_ttl: API_TOKEN_CACHE_TTL,
            session_auth_snapshot_cache_ttl: SESSION_AUTH_SNAPSHOT_CACHE_TTL,
            api_token_auth_snapshot_cache_ttl: API_TOKEN_AUTH_SNAPSHOT_CACHE_TTL,
            revocation_cache: Arc::new(RwLock::new(HashMap::new())),
            user_snapshot_cache: Arc::new(RwLock::new(HashMap::new())),
            api_token_cache: Arc::new(RwLock::new(HashMap::new())),
            session_auth_snapshot_cache: Arc::new(RwLock::new(HashMap::new())),
            api_token_auth_snapshot_cache: Arc::new(RwLock::new(HashMap::new())),
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
}

#[derive(Clone)]
struct CompatSessionAuthSnapshotChecker {
    revocation_checker: Arc<dyn RevocationChecker>,
    user_auth_snapshot_checker: Arc<dyn UserAuthSnapshotChecker>,
}

#[async_trait::async_trait]
impl SessionAuthSnapshotChecker for CompatSessionAuthSnapshotChecker {
    async fn lookup_session_auth_snapshot(
        &self,
        jti: &str,
        email: &str,
    ) -> Result<SessionAuthSnapshot, String> {
        let revoked = self.revocation_checker.is_revoked(jti).await?;
        let user = self
            .user_auth_snapshot_checker
            .lookup_user_auth_snapshot(email)
            .await?;
        Ok(SessionAuthSnapshot { revoked, user })
    }
}

#[derive(Clone)]
struct CompatApiTokenAuthSnapshotChecker {
    revocation_checker: Arc<dyn RevocationChecker>,
    user_auth_snapshot_checker: Arc<dyn UserAuthSnapshotChecker>,
    api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
}

#[async_trait::async_trait]
impl ApiTokenAuthSnapshotChecker for CompatApiTokenAuthSnapshotChecker {
    async fn lookup_api_token_auth_snapshot(
        &self,
        token: &str,
    ) -> Result<ApiTokenAuthSnapshot, String> {
        let token_record = self
            .api_token_lookup_checker
            .lookup_api_token(token)
            .await?;
        let Some(token_record) = token_record else {
            return Ok(ApiTokenAuthSnapshot {
                token: None,
                revoked: false,
                user: None,
            });
        };
        let revoked = self
            .revocation_checker
            .is_revoked(&token_record.jti)
            .await?;
        let user = self
            .user_auth_snapshot_checker
            .lookup_user_auth_snapshot(&token_record.user_email)
            .await?;
        Ok(ApiTokenAuthSnapshot {
            token: Some(token_record),
            revoked,
            user,
        })
    }
}
