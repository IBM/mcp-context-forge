// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! CLI and environment-backed configuration for the auth service.

use clap::Parser;
use std::net::SocketAddr;

#[derive(Debug, Clone, Parser)]
#[command(name = "contextforge-auth")]
#[command(about = "Experimental core-owned Rust auth service for ContextForge")]
pub struct AuthConfig {
    #[arg(long, env = "CONTEXTFORGE_AUTH_DATABASE_URL")]
    pub database_url: Option<String>,

    #[arg(
        long,
        env = "CONTEXTFORGE_AUTH_BACKEND_AUTHENTICATE_URL",
        default_value = "http://127.0.0.1:4444/_internal/core/auth/authenticate"
    )]
    pub backend_authenticate_url: String,

    #[arg(long, env = "CONTEXTFORGE_AUTH_BACKEND_HEALTH_URL")]
    pub backend_health_url: Option<String>,

    #[arg(long, env = "CONTEXTFORGE_AUTH_LISTEN_HTTP", default_value = "127.0.0.1:8788")]
    pub listen_http: String,

    #[arg(long, env = "CONTEXTFORGE_AUTH_REQUEST_TIMEOUT_MS", default_value_t = 30_000)]
    pub request_timeout_ms: u64,

    #[arg(long, env = "CONTEXTFORGE_AUTH_DB_POOL_MAX_SIZE", default_value_t = 8)]
    pub db_pool_max_size: usize,

    #[arg(long, env = "CONTEXTFORGE_AUTH_EXPERIMENTAL_DIRECT_AUTH", default_value_t = false)]
    pub experimental_direct_auth: bool,

    #[arg(long, env = "CONTEXTFORGE_AUTH_SHADOW_COMPARE_DIRECT_AUTH", default_value_t = false)]
    pub shadow_compare_direct_auth: bool,

    #[arg(long, env = "CONTEXTFORGE_AUTH_LOG", default_value = "info")]
    pub log_filter: String,

    #[arg(long, env = "JWT_SECRET_KEY", default_value = "my-test-key")]
    pub jwt_secret_key: String,

    #[arg(long, env = "JWT_ALGORITHM", default_value = "HS256")]
    pub jwt_algorithm: String,

    #[arg(long, env = "JWT_AUDIENCE", default_value = "mcpgateway-api")]
    pub jwt_audience: String,

    #[arg(long, env = "JWT_ISSUER", default_value = "mcpgateway")]
    pub jwt_issuer: String,

    #[arg(long, env = "JWT_AUDIENCE_VERIFICATION", default_value_t = true)]
    pub jwt_audience_verification: bool,

    #[arg(long, env = "JWT_ISSUER_VERIFICATION", default_value_t = true)]
    pub jwt_issuer_verification: bool,

    #[arg(long, env = "REQUIRE_TOKEN_EXPIRATION", default_value_t = true)]
    pub require_token_expiration: bool,

    #[arg(long, env = "REQUIRE_JTI", default_value_t = true)]
    pub require_jti: bool,

    #[arg(long, env = "REQUIRE_USER_IN_DB", default_value_t = false)]
    pub require_user_in_db: bool,

    #[arg(long, env = "PLATFORM_ADMIN_EMAIL", default_value = "admin@example.com")]
    pub platform_admin_email: String,
}

impl AuthConfig {
    pub fn listen_addr(&self) -> Result<SocketAddr, String> {
        self.listen_http
            .parse()
            .map_err(|err| format!("invalid CONTEXTFORGE_AUTH_LISTEN_HTTP '{}': {err}", self.listen_http))
    }
}
