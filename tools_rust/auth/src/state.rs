// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use crate::{
    config,
    db::{
        ApiTokenLookupChecker, NoopApiTokenLookupChecker, NoopUserLookupChecker, RevocationChecker,
        UserLookupChecker, build_direct_db_checkers,
    },
    error::SidecarError,
    jwt::JwtVerificationConfig,
    stats::AuthStats,
};
use reqwest::Client;
use std::{sync::Arc, time::Duration};

#[derive(Clone)]
pub struct AppState {
    pub backend_authenticate_url: Arc<str>,
    pub backend_health_url: Option<Arc<str>>,
    pub client: Client,
    pub auth_stats: Arc<AuthStats>,
    pub jwt_verification: JwtVerificationConfig,
    pub revocation_checker: Arc<dyn RevocationChecker>,
    pub user_lookup_checker: Arc<dyn UserLookupChecker>,
    pub api_token_lookup_checker: Arc<dyn ApiTokenLookupChecker>,
    pub experimental_direct_auth: bool,
    pub shadow_compare_direct_auth: bool,
    pub require_user_in_db: bool,
    pub platform_admin_email: Arc<str>,
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
}
