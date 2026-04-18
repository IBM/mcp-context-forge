// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! CLI and environment-backed configuration for the Rust A2A runtime.

use clap::Parser;
use std::{net::SocketAddr, path::PathBuf, sync::OnceLock};

/// Newtype wrapper around `OnceLock<Vec<String>>` whose `Clone` impl
/// always yields an EMPTY cache.
///
/// The field it wraps memoizes the parsed `uaid_allowed_domains` list
/// so the per-request cross-gateway path doesn't re-split on every call.
/// A plain `OnceLock<Vec<String>>` clones its contents — meaning a
/// cloned `RuntimeConfig` would carry the source's cached value and
/// silently ignore any subsequent mutation of `uaid_allowed_domains`
/// on the clone.  That's a test-isolation footgun (tests frequently
/// clone a template config and mutate fields) and it also breaks any
/// "template + override" builder pattern.
///
/// Resetting on `Clone` means each clone parses lazily against its own
/// (possibly mutated) `uaid_allowed_domains` string, which is the
/// behavior operators and tests expect.
#[derive(Debug, Default)]
pub struct CachedAllowlist(OnceLock<Vec<String>>);

impl Clone for CachedAllowlist {
    fn clone(&self) -> Self {
        Self(OnceLock::new())
    }
}

impl CachedAllowlist {
    fn get_or_init<F: FnOnce() -> Vec<String>>(&self, f: F) -> &[String] {
        self.0.get_or_init(f).as_slice()
    }
}

#[derive(Debug, Clone, Parser)]
#[command(name = "contextforge-a2a-runtime")]
#[command(about = "Experimental Rust A2A runtime sidecar for ContextForge")]
pub struct RuntimeConfig {
    #[arg(long, env = "A2A_RUST_LISTEN_HTTP", default_value = "127.0.0.1:8788")]
    pub listen_http: String,

    #[arg(long, env = "A2A_RUST_LISTEN_UDS")]
    pub listen_uds: Option<PathBuf>,

    #[arg(long, env = "A2A_RUST_REQUEST_TIMEOUT_MS", default_value_t = 30_000)]
    pub request_timeout_ms: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_CONNECT_TIMEOUT_MS",
        default_value_t = 5_000
    )]
    pub client_connect_timeout_ms: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_POOL_IDLE_TIMEOUT_SECONDS",
        default_value_t = 90
    )]
    pub client_pool_idle_timeout_seconds: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_POOL_MAX_IDLE_PER_HOST",
        default_value_t = 256
    )]
    pub client_pool_max_idle_per_host: usize,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_TCP_KEEPALIVE_SECONDS",
        default_value_t = 30
    )]
    pub client_tcp_keepalive_seconds: u64,

    #[arg(
        long,
        env = "A2A_RUST_MAX_RESPONSE_BODY_BYTES",
        default_value_t = 10_485_760
    )]
    pub max_response_body_bytes: u64,

    #[arg(long, env = "A2A_RUST_MAX_RETRIES", default_value_t = 3)]
    pub max_retries: u32,

    #[arg(long, env = "A2A_RUST_RETRY_BACKOFF_MS", default_value_t = 1_000)]
    pub retry_backoff_ms: u64,

    // --- Auth -----------------------------------------------------------
    /// Shared secret for AES-GCM decryption of encrypted auth blobs.
    /// When set, the runtime decrypts `auth_headers_encrypted` and
    /// `auth_query_params_encrypted` fields in invoke requests.
    #[arg(long, env = "A2A_RUST_AUTH_SECRET")]
    pub auth_secret: Option<String>, // pragma: allowlist secret

    // --- Backend (Python gateway) --------------------------------------
    /// Base URL of the Python gateway for proxied requests and internal
    /// authz callouts (e.g. `http://127.0.0.1:4444`).
    #[arg(
        long,
        env = "A2A_RUST_BACKEND_BASE_URL",
        default_value = "http://127.0.0.1:4444"
    )]
    pub backend_base_url: String,

    // --- Concurrency / queue -------------------------------------------
    /// Maximum number of concurrent outbound invoke batches.
    #[arg(long, env = "A2A_RUST_MAX_CONCURRENT", default_value_t = 64)]
    pub max_concurrent: usize,

    /// Optional bounded queue depth.  When set, new submissions are
    /// rejected with 503 once the queue reaches this size.
    #[arg(long, env = "A2A_RUST_MAX_QUEUED", default_value = "4096")]
    pub max_queued: Option<usize>,

    // --- Circuit breaker -----------------------------------------------
    /// Consecutive failures before a circuit opens.
    #[arg(long, env = "A2A_RUST_CIRCUIT_FAILURE_THRESHOLD", default_value_t = 5)]
    pub circuit_failure_threshold: u32,

    /// Seconds before an open circuit transitions to half-open.
    #[arg(long, env = "A2A_RUST_CIRCUIT_COOLDOWN_SECS", default_value_t = 30)]
    pub circuit_cooldown_secs: u64,

    /// Maximum tracked circuit-breaker endpoints before eviction.
    #[arg(long, env = "A2A_RUST_CIRCUIT_MAX_ENTRIES", default_value_t = 10_000)]
    pub circuit_max_entries: usize,

    // --- Metrics -------------------------------------------------------
    /// Maximum tracked per-agent metrics entries before eviction.
    #[arg(long, env = "A2A_RUST_METRICS_MAX_ENTRIES", default_value_t = 10_000)]
    pub metrics_max_entries: usize,

    // --- Agent cache ---------------------------------------------------
    /// TTL in seconds for cached agent resolve responses.
    #[arg(long, env = "A2A_RUST_AGENT_CACHE_TTL_SECS", default_value_t = 60)]
    pub agent_cache_ttl_secs: u64,

    /// Maximum cached agent entries before eviction.
    #[arg(
        long,
        env = "A2A_RUST_AGENT_CACHE_MAX_ENTRIES",
        default_value_t = 1_000
    )]
    pub agent_cache_max_entries: usize,

    // --- Redis (L2 cache) -------------------------------------------------
    /// Redis connection URL. Defaults to REDIS_URL env var.
    /// When unset, L2 caching is disabled (L1 → L3 fallback).
    #[arg(long, env = "A2A_RUST_REDIS_URL")]
    pub redis_url: Option<String>,

    /// TTL in seconds for L2 (Redis) cache entries.
    #[arg(long, env = "A2A_RUST_L2_CACHE_TTL_SECS", default_value_t = 300)]
    pub l2_cache_ttl_secs: u64,

    /// Redis pub/sub channel for cache invalidation.
    #[arg(
        long,
        env = "A2A_RUST_CACHE_INVALIDATION_CHANNEL",
        default_value = "mcpgw:a2a:invalidate"
    )]
    pub cache_invalidation_channel: String,

    // --- Session management -----------------------------------------------
    /// Enable session-based auth caching. When true and Redis is available,
    /// the sidecar creates sessions and skips Python authenticate on reuse.
    #[arg(long, env = "A2A_RUST_SESSION_ENABLED", default_value_t = true)]
    pub session_enabled: bool,

    /// TTL in seconds for session entries in Redis.
    #[arg(long, env = "A2A_RUST_SESSION_TTL_SECS", default_value_t = 300)]
    pub session_ttl_secs: u64,

    /// Comma-separated header names used for auth fingerprinting.
    #[arg(
        long,
        env = "A2A_RUST_SESSION_FINGERPRINT_HEADERS",
        default_value = "authorization,cookie,x-forwarded-for"
    )]
    pub session_fingerprint_headers: String,

    // --- Event store (streaming) ------------------------------------------
    /// Maximum events per stream in the Redis ring buffer.
    #[arg(long, env = "A2A_RUST_EVENT_STORE_MAX_EVENTS", default_value_t = 1000)]
    pub event_store_max_events: usize,

    /// TTL in seconds for event stream keys in Redis.
    #[arg(long, env = "A2A_RUST_EVENT_STORE_TTL_SECS", default_value_t = 3600)]
    pub event_store_ttl_secs: u64,

    /// Interval in milliseconds for flushing events to PG via Python RPC.
    #[arg(long, env = "A2A_RUST_EVENT_FLUSH_INTERVAL_MS", default_value_t = 1000)]
    pub event_flush_interval_ms: u64,

    /// Maximum events per PG flush batch.
    #[arg(long, env = "A2A_RUST_EVENT_FLUSH_BATCH_SIZE", default_value_t = 100)]
    pub event_flush_batch_size: usize,

    // --- UAID cross-gateway routing (HCS-14) --------------------------
    /// Comma-separated allowlist of domains for UAID cross-gateway routing.
    /// Match semantics: exact host OR proper subdomain (host ends with
    /// `.{domain}`).  Empty value disables the allowlist — unsafe; a warning
    /// is logged at startup.
    #[arg(long, env = "A2A_RUST_UAID_ALLOWED_DOMAINS", default_value = "")]
    pub uaid_allowed_domains: String,

    /// Maximum UAID string length (DoS cap enforced during parsing).  Must
    /// fit the Python `a2a_agents.uaid` column (VARCHAR(2048)) so UAIDs
    /// generated by Python are still parseable here.
    #[arg(long, env = "A2A_RUST_UAID_MAX_LENGTH", default_value_t = 2048)]
    pub uaid_max_length: usize,

    /// Maximum UAID cross-gateway federation hops.  Every outbound
    /// cross-gateway POST from `handle_uaid_cross_gateway(_streaming)`
    /// stamps `X-Contextforge-UAID-Hop: N+1`; inbound requests at or
    /// above this limit are rejected with 404 to break recursion.
    /// Default 5 matches Python's `uaid_max_federation_hops` default
    /// and accommodates multi-tenant partner chains while still
    /// terminating loops quickly.
    #[arg(long, env = "A2A_RUST_UAID_MAX_FEDERATION_HOPS", default_value_t = 5)]
    pub uaid_max_federation_hops: u32,

    /// Memoized parse of `uaid_allowed_domains` — populated on first
    /// call to [`RuntimeConfig::uaid_allowed_domains_list`] and reused
    /// thereafter so the per-request cross-gateway code path doesn't
    /// re-split on every invocation.  Uses [`CachedAllowlist`] so that
    /// cloning a `RuntimeConfig` resets the cache to empty — matches
    /// test-isolation expectations when a template config is cloned
    /// and its `uaid_allowed_domains` mutated.  `#[clap(skip)]` excludes
    /// it from CLI/env parsing.
    #[clap(skip)]
    pub uaid_allowed_domains_cache: CachedAllowlist,

    // --- Logging / lifecycle -------------------------------------------
    #[arg(long, env = "A2A_RUST_LOG", default_value = "info")]
    pub log_filter: String,

    #[arg(long, env = "A2A_RUST_EXIT_AFTER_STARTUP_MS", hide = true)]
    pub exit_after_startup_ms: Option<u64>,
}

#[derive(Debug, Clone)]
pub enum ListenTarget {
    Http(SocketAddr),
    Uds(PathBuf),
}

impl RuntimeConfig {
    /// Parse the comma-separated `uaid_allowed_domains` into a cleaned
    /// list.  Empty entries and whitespace are stripped so the common
    /// "unset" form (empty env var) yields an empty list, not `[""]`.
    ///
    /// Memoized via `uaid_allowed_domains_cache` so the per-request
    /// cross-gateway path doesn't re-split + re-allocate on every call.
    /// Returns a borrowed slice; callers that need ownership can
    /// `.to_vec()` it explicitly.
    pub fn uaid_allowed_domains_list(&self) -> &[String] {
        self.uaid_allowed_domains_cache.get_or_init(|| {
            self.uaid_allowed_domains
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect()
        })
    }

    pub fn listen_target(&self) -> Result<ListenTarget, String> {
        if let Some(path) = &self.listen_uds {
            return Ok(ListenTarget::Uds(path.clone()));
        }

        self.listen_http
            .parse::<SocketAddr>()
            .map(ListenTarget::Http)
            .map_err(|err| {
                format!(
                    "invalid A2A_RUST_LISTEN_HTTP value '{}': {err}",
                    self.listen_http
                )
            })
    }

    /// Cross-field validation invoked by [`crate::run`] at startup.
    ///
    /// Clap handles per-field parsing, but several invariants cross multiple
    /// fields.  Catching these at startup beats surfacing them as strange
    /// runtime behaviour (timeouts that can never trigger, retry budgets
    /// that exceed the client timeout, etc.).
    pub fn validate_cross_field(&self) -> Result<(), String> {
        if self.max_concurrent == 0 {
            return Err("A2A_RUST_MAX_CONCURRENT must be >= 1".to_string());
        }
        if self.agent_cache_max_entries == 0 {
            return Err("A2A_RUST_AGENT_CACHE_MAX_ENTRIES must be >= 1".to_string());
        }
        if self.circuit_failure_threshold == 0 {
            return Err("A2A_RUST_CIRCUIT_FAILURE_THRESHOLD must be >= 1".to_string());
        }

        // Retry budget: total backoff (sum of geometric series up to
        // max_retries * retry_backoff_ms) should fit within the per-request
        // timeout, or the circuit breaker will trip before retries even run.
        // Use a conservative upper bound: max_retries * retry_backoff_ms.
        let retry_budget_ms = self
            .retry_backoff_ms
            .saturating_mul(u64::from(self.max_retries));
        if retry_budget_ms > self.request_timeout_ms {
            return Err(format!(
                "retry budget ({}ms = {} retries × {}ms backoff) exceeds request timeout ({}ms); \
                 retries can never complete",
                retry_budget_ms, self.max_retries, self.retry_backoff_ms, self.request_timeout_ms
            ));
        }

        // Cache TTL sanity: L2 (Redis, shared) should outlive L1 (in-process)
        // so a node restart does not reload a stale-by-comparison entry from
        // L2.  Allow equality (both set to the same value) for simple
        // deployments.
        if self.l2_cache_ttl_secs > 0 && self.l2_cache_ttl_secs < self.agent_cache_ttl_secs {
            return Err(format!(
                "A2A_RUST_L2_CACHE_TTL_SECS ({}) must be >= A2A_RUST_AGENT_CACHE_TTL_SECS ({})",
                self.l2_cache_ttl_secs, self.agent_cache_ttl_secs
            ));
        }

        // Session TTL: when sessions are enabled, the session must outlive
        // a typical request round-trip; otherwise fast-path cache hits will
        // never trigger.
        if self.session_enabled && self.session_ttl_secs == 0 {
            return Err(
                "A2A_RUST_SESSION_TTL_SECS must be > 0 when sessions are enabled".to_string(),
            );
        }

        // Federation hop cap: mirror Python's `Field(ge=1, le=10)` in
        // `mcpgateway/config.py` so operators can't accidentally set 0
        // (rejects every request as at-limit) or a runaway value that
        // defeats loop protection in practice.  10 is enough for any
        // realistic multi-tenant federation chain.
        if self.uaid_max_federation_hops == 0 || self.uaid_max_federation_hops > 10 {
            return Err(format!(
                "A2A_RUST_UAID_MAX_FEDERATION_HOPS must be in 1..=10 (matches Python's Field(ge=1, le=10)); got {}",
                self.uaid_max_federation_hops
            ));
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    /// Returns a RuntimeConfig with sensible defaults for unit testing.
    fn test_config() -> RuntimeConfig {
        RuntimeConfig {
            listen_http: "127.0.0.1:8788".to_string(),
            listen_uds: None,
            request_timeout_ms: 30_000,
            client_connect_timeout_ms: 5_000,
            client_pool_idle_timeout_seconds: 90,
            client_pool_max_idle_per_host: 256,
            client_tcp_keepalive_seconds: 30,
            max_response_body_bytes: 10_485_760,
            max_retries: 3,
            retry_backoff_ms: 1_000,
            auth_secret: None,
            backend_base_url: "http://127.0.0.1:4444".to_string(),
            max_concurrent: 64,
            max_queued: Some(4096),
            circuit_failure_threshold: 5,
            circuit_cooldown_secs: 30,
            circuit_max_entries: 10_000,
            metrics_max_entries: 10_000,
            agent_cache_ttl_secs: 60,
            agent_cache_max_entries: 1_000,
            redis_url: None,
            l2_cache_ttl_secs: 300,
            cache_invalidation_channel: "mcpgw:a2a:invalidate".to_string(),
            session_enabled: true,
            session_ttl_secs: 300,
            session_fingerprint_headers: "authorization,cookie,x-forwarded-for".to_string(),
            event_store_max_events: 1000,
            event_store_ttl_secs: 3600,
            event_flush_interval_ms: 1000,
            event_flush_batch_size: 100,
            uaid_allowed_domains: String::new(),
            uaid_allowed_domains_cache: CachedAllowlist::default(),
            uaid_max_length: 2048,
            uaid_max_federation_hops: 3,
            log_filter: "info".to_string(),
            exit_after_startup_ms: None,
        }
    }

    #[test]
    fn listen_target_parses_valid_http_address() {
        let config = test_config();
        let target = config.listen_target().expect("should parse valid address");
        assert!(matches!(
            target,
            ListenTarget::Http(addr) if addr == "127.0.0.1:8788".parse::<SocketAddr>().unwrap()
        ));
    }

    #[test]
    fn listen_target_prefers_uds_over_http() {
        let mut config = test_config();
        config.listen_uds = Some(PathBuf::from("/tmp/test.sock"));
        let target = config.listen_target().expect("should return Uds");
        assert!(matches!(
            target,
            ListenTarget::Uds(path) if path == std::path::Path::new("/tmp/test.sock")
        ));
    }

    #[test]
    fn listen_target_rejects_invalid_address() {
        let mut config = test_config();
        config.listen_http = "not-an-address".to_string();
        let result = config.listen_target();
        assert!(result.is_err(), "expected Err for invalid address, got Ok");
    }

    #[test]
    fn default_config_values_are_sensible() {
        let config = RuntimeConfig::parse_from(["test"]);
        assert_eq!(config.listen_http, "127.0.0.1:8788");
        assert_eq!(config.request_timeout_ms, 30_000);
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.max_queued, Some(4096));
        assert_eq!(config.circuit_failure_threshold, 5);
        assert!(config.session_enabled);
        assert_eq!(config.event_store_max_events, 1000);
    }

    #[test]
    fn validate_cross_field_accepts_defaults() {
        let config = test_config();
        assert!(config.validate_cross_field().is_ok());
    }

    #[test]
    fn validate_cross_field_rejects_zero_max_concurrent() {
        let mut config = test_config();
        config.max_concurrent = 0;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("MAX_CONCURRENT"));
    }

    #[test]
    fn validate_cross_field_rejects_retry_budget_exceeding_timeout() {
        // 5 retries × 1000ms backoff = 5000ms retry budget,
        // but request timeout is only 2000ms — retries cannot complete.
        let mut config = test_config();
        config.request_timeout_ms = 2_000;
        config.retry_backoff_ms = 1_000;
        config.max_retries = 5;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("retry budget"));
        assert!(err.contains("exceeds request timeout"));
    }

    #[test]
    fn validate_cross_field_rejects_l2_ttl_shorter_than_l1() {
        // L2 (Redis, shared) should outlive L1 or node restarts reload stale data.
        let mut config = test_config();
        config.agent_cache_ttl_secs = 600;
        config.l2_cache_ttl_secs = 60;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("L2_CACHE_TTL_SECS"));
    }

    #[test]
    fn validate_cross_field_rejects_zero_session_ttl_when_sessions_enabled() {
        let mut config = test_config();
        config.session_enabled = true;
        config.session_ttl_secs = 0;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("SESSION_TTL_SECS"));
    }

    #[test]
    fn validate_cross_field_rejects_zero_agent_cache_entries() {
        let mut config = test_config();
        config.agent_cache_max_entries = 0;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("AGENT_CACHE_MAX_ENTRIES"));
    }

    #[test]
    fn validate_cross_field_rejects_zero_circuit_failure_threshold() {
        let mut config = test_config();
        config.circuit_failure_threshold = 0;
        let err = config.validate_cross_field().expect_err("should reject");
        assert!(err.contains("CIRCUIT_FAILURE_THRESHOLD"));
    }

    #[test]
    fn validate_cross_field_allows_zero_session_ttl_when_sessions_disabled() {
        let mut config = test_config();
        config.session_enabled = false;
        config.session_ttl_secs = 0;
        assert!(config.validate_cross_field().is_ok());
    }

    #[test]
    fn validate_cross_field_rejects_zero_uaid_max_federation_hops() {
        let mut config = test_config();
        config.uaid_max_federation_hops = 0;
        let err = config
            .validate_cross_field()
            .expect_err("0 must be rejected");
        assert!(err.contains("UAID_MAX_FEDERATION_HOPS"), "err={err}");
    }

    #[test]
    fn validate_cross_field_rejects_uaid_max_federation_hops_above_ten() {
        let mut config = test_config();
        config.uaid_max_federation_hops = 11;
        let err = config
            .validate_cross_field()
            .expect_err("11 must be rejected");
        assert!(err.contains("UAID_MAX_FEDERATION_HOPS"), "err={err}");
    }

    #[test]
    fn validate_cross_field_accepts_uaid_max_federation_hops_at_bounds() {
        // 1 and 10 are both valid; regression guard against an off-by-one
        // that would reject the exclusive bound values.
        let mut config = test_config();
        config.uaid_max_federation_hops = 1;
        assert!(config.validate_cross_field().is_ok());
        config.uaid_max_federation_hops = 10;
        assert!(config.validate_cross_field().is_ok());
    }

    #[test]
    fn clone_resets_uaid_allowed_domains_cache() {
        // Template config has allowlist A; cloning then mutating the
        // allowlist on the clone and asking for the parsed list must
        // yield the NEW value, not A's cached result.  Prior
        // `Arc<OnceLock>` shape aliased the cache across clones so the
        // mutation was silently ignored — a nasty test-isolation
        // footgun for any "template + override" pattern.
        let mut config = test_config();
        config.uaid_allowed_domains = "original.example.com".to_string();
        // Prime the source cache.
        assert_eq!(config.uaid_allowed_domains_list(), ["original.example.com"]);

        let mut clone = config.clone();
        clone.uaid_allowed_domains = "replaced.example.com".to_string();
        assert_eq!(
            clone.uaid_allowed_domains_list(),
            ["replaced.example.com"],
            "cloned config must reparse its own (mutated) allowlist, not reuse the template's cache"
        );
        // The original must keep its cached value undisturbed.
        assert_eq!(config.uaid_allowed_domains_list(), ["original.example.com"]);
    }
}
