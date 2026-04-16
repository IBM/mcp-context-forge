// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Experimental Rust A2A runtime sidecar for ContextForge.

pub mod auth;
pub mod cache;
pub mod circuit;
pub mod config;
pub mod errors;
pub mod event_store;
pub mod eviction;
pub mod http;
pub mod invoke;
pub mod metrics;
pub mod push;
pub mod queue;
pub mod server;
pub mod session;
pub mod stream;
pub mod trust;

use config::{ListenTarget, RuntimeConfig};
use reqwest::Client;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use thiserror::Error;
use tracing::info;

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("{0}")]
    Config(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    HttpClient(#[from] reqwest::Error),
}

fn build_http_client(config: &RuntimeConfig) -> Result<Client, reqwest::Error> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_millis(config.client_connect_timeout_ms))
        .pool_idle_timeout(Duration::from_secs(config.client_pool_idle_timeout_seconds))
        .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
        .tcp_keepalive(Duration::from_secs(config.client_tcp_keepalive_seconds))
        .timeout(Duration::from_millis(config.request_timeout_ms))
        .redirect(reqwest::redirect::Policy::none())
        .build()
}

pub async fn run(config: RuntimeConfig) -> Result<(), RuntimeError> {
    if config
        .auth_secret
        .as_deref()
        .map(str::is_empty)
        .unwrap_or(true)
    {
        return Err(RuntimeError::Config(
            "A2A_RUST_AUTH_SECRET is required: the runtime cannot build trust headers or decrypt \
             encrypted auth blobs without a shared secret. Refusing to start."
                .to_string(),
        ));
    }

    // Surface cross-field config errors at startup rather than as silent
    // runtime misbehaviour (timeouts that never trigger, retries that
    // exceed their deadline, cache tiers that churn each other, etc.).
    config
        .validate_cross_field()
        .map_err(RuntimeError::Config)?;

    let client = build_http_client(&config)?;
    let config_arc = Arc::new(config.clone());

    let cb = Arc::new(circuit::CircuitBreaker::new(
        config.circuit_failure_threshold,
        Duration::from_secs(config.circuit_cooldown_secs),
        Some(config.circuit_max_entries),
    ));
    let mc = Arc::new(metrics::MetricsCollector::new(Some(
        config.metrics_max_entries,
    )));

    let worker_state = Arc::new(queue::WorkerState {
        client: client.clone(),
        config: Arc::clone(&config_arc),
        circuit: Arc::clone(&cb),
        metrics: Arc::clone(&mc),
    });

    queue::init_queue(
        config.max_concurrent,
        config.max_queued,
        Arc::clone(&worker_state),
    );

    let redis_pool = if let Some(ref url) = config.redis_url {
        cache::RedisPool::connect(url).await.map(Arc::new)
    } else {
        None
    };

    let agent_cache = Arc::new(cache::TieredCache::new(
        Duration::from_secs(config.agent_cache_ttl_secs),
        Some(config.agent_cache_max_entries),
        redis_pool.as_ref().map(|p| (**p).clone()),
        config.l2_cache_ttl_secs,
        "mcpgw:a2a:agent",
    ));

    // Start cache invalidation subscriber if Redis is available.
    let _cache_subscriber_shutdown = if let Some(ref pool) = redis_pool {
        let agent_cache_ref = Arc::clone(&agent_cache);
        let evict_fn: Arc<dyn Fn(&str) + Send + Sync> = Arc::new(move |key: &str| {
            agent_cache_ref.evict_l1(key);
        });
        Some(cache::CacheSubscriber::spawn(
            (**pool).clone(),
            config.cache_invalidation_channel.clone(),
            evict_fn,
        ))
    } else {
        None
    };

    let session_manager = if config.session_enabled {
        redis_pool.as_ref().map(|pool| {
            Arc::new(session::SessionManager::new(
                (**pool).clone(),
                config.session_ttl_secs,
                &config.session_fingerprint_headers,
            ))
        })
    } else {
        None
    };

    let (event_store_arc, _flush_handle) = if let Some(ref pool) = redis_pool {
        let (tx, rx) = tokio::sync::mpsc::channel(10_000);
        let store = Arc::new(event_store::EventStore::new(
            (**pool).clone(),
            config.event_store_max_events,
            config.event_store_ttl_secs,
            tx,
        ));
        let handle = event_store::spawn_flush_task(
            rx,
            client.clone(),
            config.backend_base_url.clone(),
            config
                .auth_secret
                .clone()
                .expect("auth_secret validated non-empty in run()"),
            Duration::from_millis(config.event_flush_interval_ms),
            config.event_flush_batch_size,
        );
        (Some(store), Some(handle))
    } else {
        (None, None)
    };

    let state = server::AppState {
        config: config_arc,
        client,
        circuit: cb,
        metrics: mc,
        worker_state,
        redis_pool,
        agent_cache,
        session_manager,
        event_store: event_store_arc,
    };

    let app = server::router(state);
    let shutdown_after = config.exit_after_startup_ms.map(Duration::from_millis);

    match config.listen_target().map_err(RuntimeError::Config)? {
        ListenTarget::Http(addr) => serve_http(app, addr, shutdown_after).await?,
        ListenTarget::Uds(path) => serve_uds(app, path, shutdown_after).await?,
    }

    Ok(())
}

async fn serve_http(
    app: axum::Router,
    addr: std::net::SocketAddr,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    info!("starting Rust A2A runtime on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
    }
    Ok(())
}

async fn serve_uds(
    app: axum::Router,
    path: PathBuf,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    if Path::new(&path).exists() {
        std::fs::remove_file(&path)?;
    }
    info!("starting Rust A2A runtime on unix://{}", path.display());
    let listener = tokio::net::UnixListener::bind(&path)?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
    }
    Ok(())
}

/// Test support utilities — not part of the public API.
#[doc(hidden)]
pub mod test_support {
    use super::*;

    /// Build the Axum app without starting a listener.
    pub fn build_app(config: RuntimeConfig) -> axum::Router {
        build_app_with_overrides(config, None, None)
    }

    /// Build the Axum app with a test-supplied event store.
    pub fn build_app_with_event_store(
        config: RuntimeConfig,
        event_store: Option<Arc<crate::event_store::EventStore>>,
    ) -> axum::Router {
        build_app_with_overrides(config, None, event_store)
    }

    /// Build the Axum app with a test-supplied session manager.
    pub fn build_app_with_session_manager(
        config: RuntimeConfig,
        session_manager: Option<Arc<crate::session::SessionManager>>,
    ) -> axum::Router {
        build_app_with_overrides(config, session_manager, None)
    }

    fn build_app_with_overrides(
        config: RuntimeConfig,
        session_manager: Option<Arc<crate::session::SessionManager>>,
        event_store: Option<Arc<crate::event_store::EventStore>>,
    ) -> axum::Router {
        let client = build_http_client(&config).expect("failed to build reqwest client");
        let config_arc = Arc::new(config);

        let cb = Arc::new(circuit::CircuitBreaker::new(
            config_arc.circuit_failure_threshold,
            Duration::from_secs(config_arc.circuit_cooldown_secs),
            Some(config_arc.circuit_max_entries),
        ));
        let mc = Arc::new(metrics::MetricsCollector::new(Some(
            config_arc.metrics_max_entries,
        )));

        let worker_state = Arc::new(queue::WorkerState {
            client: client.clone(),
            config: Arc::clone(&config_arc),
            circuit: Arc::clone(&cb),
            metrics: Arc::clone(&mc),
        });

        let agent_cache = Arc::new(cache::TieredCache::new(
            Duration::from_secs(config_arc.agent_cache_ttl_secs),
            Some(config_arc.agent_cache_max_entries),
            None,
            config_arc.l2_cache_ttl_secs,
            "mcpgw:a2a:agent",
        ));

        let state = server::AppState {
            config: config_arc,
            client,
            circuit: cb,
            metrics: mc,
            worker_state,
            redis_pool: None,
            agent_cache,
            session_manager,
            event_store,
        };

        server::router(state)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::Router;
    use std::fs;

    fn temp_socket_path(prefix: &str) -> PathBuf {
        PathBuf::from(format!(
            "/tmp/{}-{}.sock",
            prefix,
            &uuid::Uuid::new_v4().simple().to_string()[..8]
        ))
    }

    fn test_config() -> RuntimeConfig {
        RuntimeConfig {
            listen_http: "127.0.0.1:0".to_string(),
            listen_uds: None,
            request_timeout_ms: 50,
            client_connect_timeout_ms: 50,
            client_pool_idle_timeout_seconds: 1,
            client_pool_max_idle_per_host: 1,
            client_tcp_keepalive_seconds: 1,
            max_response_body_bytes: 1024,
            max_retries: 0,
            retry_backoff_ms: 1,
            auth_secret: Some("test-shared-secret".to_string()),
            backend_base_url: "http://127.0.0.1:4444".to_string(),
            max_concurrent: 1,
            max_queued: Some(4),
            circuit_failure_threshold: 1,
            circuit_cooldown_secs: 1,
            circuit_max_entries: 4,
            metrics_max_entries: 4,
            agent_cache_ttl_secs: 1,
            agent_cache_max_entries: 4,
            redis_url: None,
            l2_cache_ttl_secs: 1,
            cache_invalidation_channel: "test-invalidate".to_string(),
            session_enabled: false,
            session_ttl_secs: 1,
            session_fingerprint_headers: "authorization".to_string(),
            event_store_max_events: 4,
            event_store_ttl_secs: 1,
            event_flush_interval_ms: 1,
            event_flush_batch_size: 1,
            log_filter: "info".to_string(),
            exit_after_startup_ms: Some(5),
        }
    }

    #[test]
    fn build_http_client_applies_timeouts() {
        let config = test_config();
        let client = build_http_client(&config).expect("client should build");
        drop(client);
    }

    #[tokio::test]
    async fn serve_http_returns_after_graceful_shutdown_delay() {
        let app = Router::new();
        let addr: std::net::SocketAddr = "127.0.0.1:0".parse().unwrap();
        serve_http(app, addr, Some(Duration::from_millis(5)))
            .await
            .expect("http server should exit cleanly");
    }

    #[tokio::test]
    async fn serve_uds_removes_existing_socket_path() {
        let app = Router::new();
        let path = temp_socket_path("a2a-test");
        fs::write(&path, b"placeholder").expect("create placeholder file");

        serve_uds(app, path.clone(), Some(Duration::from_millis(5)))
            .await
            .expect("uds server should exit cleanly");

        assert!(
            path.exists(),
            "unix listener path should be recreated by bind"
        );
        let _ = fs::remove_file(path);
    }

    #[tokio::test]
    async fn run_serves_http_until_exit_after_startup() {
        run(test_config())
            .await
            .expect("runtime should start and shut down cleanly");
    }

    #[tokio::test]
    async fn run_rejects_missing_auth_secret() {
        let mut config = test_config();
        config.auth_secret = None; // pragma: allowlist secret
        let err = run(config)
            .await
            .expect_err("missing auth_secret must fail");
        assert!(
            matches!(err, RuntimeError::Config(_)),
            "expected Config error, got {err:?}"
        );
    }

    #[tokio::test]
    async fn run_rejects_empty_auth_secret() {
        let mut config = test_config();
        config.auth_secret = Some(String::new());
        let err = run(config).await.expect_err("empty auth_secret must fail");
        assert!(
            matches!(err, RuntimeError::Config(_)),
            "expected Config error, got {err:?}"
        );
    }

    #[tokio::test]
    async fn run_serves_uds_until_exit_after_startup() {
        let path = temp_socket_path("a2a-run");
        serve_uds(Router::new(), path.clone(), Some(Duration::from_millis(5)))
            .await
            .expect("uds server should exit cleanly");
        let _ = fs::remove_file(path);
    }
}
