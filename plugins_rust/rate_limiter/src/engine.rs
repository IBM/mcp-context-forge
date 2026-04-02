// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// `RateLimiterEngine` — the single PyO3-exposed class (IFACE-02).
//
// Python calls `check(user, tenant, tool, now_unix)` once per hook
// invocation (ARCH-01).  The engine builds dimension keys, evaluates,
// aggregates, and returns pre-built header/meta dicts (ARCH-02).
// The Python wrapper is policy-only and never does rate math (ARCH-03).
//
// The older `evaluate_many()` / `evaluate_many_async()` entry points are
// retained for backward compatibility and test use but are not on the
// production hot path.

use std::collections::HashMap;
use std::sync::Arc;

use log::warn;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use pyo3_async_runtimes::tokio::future_into_py;
use pyo3_stub_gen::derive::*;

use crate::clock::{Clock, SystemClock};
use crate::config::{ConfigError, EngineConfig};
use crate::memory::MemoryStore;
use crate::redis_backend::RedisRateLimiter;
use crate::types::{DimResult, EvalResult};

// ---------------------------------------------------------------------------
// Backend selection
// ---------------------------------------------------------------------------

#[derive(Clone)]
enum EngineBackend {
    Memory(Arc<MemoryStore>),
    Redis(Arc<RedisRateLimiter>),
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

/// High-performance rate limiter engine.
///
/// Construct once per plugin instance (`__init__`), then call
/// `check()` / `check_async()` on every hook invocation.
///
/// Backend is selected at init time from the config dict:
/// - `backend: "memory"` (default) — in-process counting via `MemoryStore`
/// - `backend: "redis"` — Rust owns the Redis connection; same batch Lua
///   scripts as the Python `RedisBackend`, one EVAL per hook invocation
#[gen_stub_pyclass]
#[pyclass]
pub struct RateLimiterEngine {
    config: EngineConfig,
    backend: EngineBackend,
    clock: Arc<dyn Clock>,
}

impl RateLimiterEngine {
    /// Internal constructor — always uses the memory backend.
    /// Used by tests and benchmarks where clock injection is required.
    pub fn new_with_clock(config: EngineConfig, clock: Arc<dyn Clock>) -> Self {
        Self {
            backend: EngineBackend::Memory(Arc::new(MemoryStore::new())),
            config,
            clock,
        }
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl RateLimiterEngine {
    /// Construct from the Python config dict.
    ///
    /// Parses all rate strings and normalises `by_tool` keys at init time —
    /// never on the request path (IFACE-01, IFACE-05).
    ///
    /// Extra keys consumed here (not part of `EngineConfig`):
    /// - `backend`: `"memory"` (default) or `"redis"`
    /// - `redis_url`: required when `backend = "redis"`
    /// - `redis_key_prefix`: key namespace prefix (default `"rl"`)
    #[new]
    pub fn new(config: &Bound<'_, PyDict>) -> PyResult<Self> {
        let by_user: Option<String> = match config.get_item("by_user")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>().map_err(|_| {
                pyo3::exceptions::PyValueError::new_err("by_user must be a string like '60/m'")
            })?),
            _ => None,
        };
        let by_tenant: Option<String> = match config.get_item("by_tenant")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>().map_err(|_| {
                pyo3::exceptions::PyValueError::new_err("by_tenant must be a string like '600/m'")
            })?),
            _ => None,
        };
        let algorithm: String = match config.get_item("algorithm")? {
            Some(v) if !v.is_none() => v.extract::<String>().map_err(|_| {
                pyo3::exceptions::PyValueError::new_err(
                    "algorithm must be a string ('fixed_window', 'sliding_window', or 'token_bucket')",
                )
            })?,
            _ => "fixed_window".to_string(),
        };

        let by_tool: HashMap<String, String> = match config.get_item("by_tool")? {
            Some(v) if !v.is_none() => v.extract::<HashMap<String, String>>().map_err(|_| {
                pyo3::exceptions::PyValueError::new_err(
                    "by_tool must be a dict of {tool_name: rate_string}",
                )
            })?,
            _ => HashMap::new(),
        };

        let engine_config = EngineConfig::new(
            by_user.as_deref(),
            by_tenant.as_deref(),
            by_tool,
            &algorithm,
        )
        .map_err(|e: ConfigError| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let backend_str: String = config
            .get_item("backend")?
            .and_then(|v| v.extract().ok())
            .unwrap_or_else(|| "memory".to_string());

        let backend = if backend_str == "redis" {
            let redis_url: String = config
                .get_item("redis_url")?
                .and_then(|v| v.extract().ok())
                .ok_or_else(|| {
                    pyo3::exceptions::PyValueError::new_err(
                        "redis_url is required when backend=redis",
                    )
                })?;
            let prefix: String = config
                .get_item("redis_key_prefix")?
                .and_then(|v| v.extract().ok())
                .unwrap_or_else(|| "rl".to_string());
            let redis_limiter = RedisRateLimiter::new(&redis_url, engine_config.algorithm, prefix)
                .map_err(|e| {
                    warn!("Rust rate limiter: Redis backend init failed: {}", e);
                    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
                })?;
            EngineBackend::Redis(Arc::new(redis_limiter))
        } else {
            EngineBackend::Memory(Arc::new(MemoryStore::new()))
        };

        Ok(Self {
            config: engine_config,
            backend,
            clock: Arc::new(SystemClock),
        })
    }

    /// Evaluate all active dimensions in a single call (ARCH-01, IFACE-02).
    ///
    /// `checks` is a list of `(key, limit_count, window_nanos)` tuples built
    /// by the Python wrapper from the request context.
    ///
    /// `now_unix` is `int(time.time())` from Python — passing it here means
    /// Python test mocks of `time.time()` propagate to header timestamps (CORR-02).
    ///
    /// Returns the most restrictive `EvalResult` across all dimensions (ARCH-02).
    ///
    /// **Warning:** For the Redis backend, this method calls `block_on` on a
    /// dedicated Tokio runtime.  It must not be called from within an existing
    /// Tokio runtime (e.g. from `pyo3-async-runtimes` worker threads) or it
    /// will panic.  Use `evaluate_many_async` for async contexts instead.
    pub fn evaluate_many(
        &self,
        checks: Vec<(String, u64, u64)>,
        now_unix: i64,
    ) -> PyResult<EvalResult> {
        let dim_results = eval_dims_sync(
            &self.backend,
            self.config.algorithm,
            &self.clock,
            checks,
            now_unix,
        )?;
        Ok(EvalResult::from_dims(&dim_results))
    }

    /// Evaluate all active dimensions asynchronously.
    ///
    /// Intended for Redis-backed deployments so Python async hooks can await
    /// the Rust Redis path without blocking the event loop.
    pub fn evaluate_many_async<'py>(
        &self,
        py: Python<'py>,
        checks: Vec<(String, u64, u64)>,
        now_unix: i64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let backend = self.backend.clone();
        let algorithm = self.config.algorithm;
        let clock = Arc::clone(&self.clock);

        future_into_py(py, async move {
            let dim_results = eval_dims_async(backend, algorithm, clock, checks, now_unix).await?;
            Python::attach(|py| Py::new(py, EvalResult::from_dims(&dim_results)))
        })
    }

    /// High-level check: builds dimension keys internally, evaluates, and
    /// returns pre-built Python dicts for headers and metadata.
    ///
    /// This eliminates all per-attribute PyO3 accesses on the Python side.
    /// The Python wrapper calls this once per hook invocation instead of
    /// `evaluate_many()` + `_rust_to_plugin_meta()` + `_rust_to_plugin_headers()`.
    ///
    /// Returns `(allowed, headers_dict, meta_dict)`.
    pub fn check<'py>(
        &self,
        py: Python<'py>,
        user: &str,
        tenant: Option<&str>,
        tool: &str,
        now_unix: i64,
        include_retry_after: bool,
    ) -> PyResult<(bool, Bound<'py, PyDict>, Bound<'py, PyDict>)> {
        let checks = self.build_checks(user, tenant, tool);
        if checks.is_empty() {
            let headers = PyDict::new(py);
            let meta = PyDict::new(py);
            meta.set_item("limited", false)?;
            return Ok((true, headers, meta));
        }

        let dim_results = eval_dims_sync(
            &self.backend,
            self.config.algorithm,
            &self.clock,
            checks,
            now_unix,
        )?;

        let eval = EvalResult::from_dims(&dim_results);
        let headers = build_headers_dict(py, &eval, include_retry_after)?;
        let meta = build_meta_dict(py, &eval, now_unix)?;
        Ok((eval.allowed, headers, meta))
    }

    /// Async variant of `check()` for Redis-backed deployments.
    ///
    /// Returns an awaitable that resolves to `(allowed, headers_dict, meta_dict)`.
    pub fn check_async<'py>(
        &self,
        py: Python<'py>,
        user: &str,
        tenant: Option<&str>,
        tool: &str,
        now_unix: i64,
        include_retry_after: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let checks = self.build_checks(user, tenant, tool);
        if checks.is_empty() {
            return future_into_py(py, async move {
                Python::attach(|py| -> PyResult<Py<PyAny>> {
                    let headers = PyDict::new(py);
                    let meta = PyDict::new(py);
                    meta.set_item("limited", false)?;
                    let tup = pyo3::types::PyTuple::new(
                        py,
                        [
                            true.into_pyobject(py)?.to_owned().into_any(),
                            headers.into_any(),
                            meta.into_any(),
                        ],
                    )?;
                    Ok(tup.into())
                })
            });
        }

        let backend = self.backend.clone();
        let algorithm = self.config.algorithm;
        let clock = Arc::clone(&self.clock);

        future_into_py(py, async move {
            let dim_results = eval_dims_async(backend, algorithm, clock, checks, now_unix).await?;

            let eval = EvalResult::from_dims(&dim_results);
            Python::attach(|py| -> PyResult<Py<PyAny>> {
                let headers = build_headers_dict(py, &eval, include_retry_after)?;
                let meta = build_meta_dict(py, &eval, now_unix)?;
                let tup = pyo3::types::PyTuple::new(
                    py,
                    [
                        eval.allowed.into_pyobject(py)?.to_owned().into_any(),
                        headers.into_any(),
                        meta.into_any(),
                    ],
                )?;
                Ok(tup.into())
            })
        })
    }
}

// ---------------------------------------------------------------------------
// Shared dimension evaluation — used by evaluate_many, check (sync + async)
// ---------------------------------------------------------------------------

/// Evaluate dimension checks synchronously (memory: GIL-released, Redis: block_on).
fn eval_dims_sync(
    backend: &EngineBackend,
    algorithm: crate::config::Algorithm,
    clock: &Arc<dyn Clock>,
    checks: Vec<(String, u64, u64)>,
    now_unix: i64,
) -> PyResult<Vec<DimResult>> {
    Python::attach(|py| {
        py.detach(|| -> Result<Vec<DimResult>, String> {
            eval_dims_inner(backend, algorithm, clock, checks, now_unix)
        })
        .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    })
}

/// Evaluate dimension checks asynchronously (memory: direct, Redis: async).
async fn eval_dims_async(
    backend: EngineBackend,
    algorithm: crate::config::Algorithm,
    clock: Arc<dyn Clock>,
    checks: Vec<(String, u64, u64)>,
    now_unix: i64,
) -> PyResult<Vec<DimResult>> {
    match backend {
        EngineBackend::Memory(store) => {
            let now_mono = clock.now_monotonic();
            Ok(eval_dims_memory(
                &store, algorithm, checks, now_mono, now_unix,
            ))
        }
        EngineBackend::Redis(redis) => redis
            .evaluate_many_async(&checks, now_unix)
            .await
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
    }
}

/// Backend dispatch for synchronous evaluation (called inside `py.detach`).
fn eval_dims_inner(
    backend: &EngineBackend,
    algorithm: crate::config::Algorithm,
    clock: &Arc<dyn Clock>,
    checks: Vec<(String, u64, u64)>,
    now_unix: i64,
) -> Result<Vec<DimResult>, String> {
    match backend {
        EngineBackend::Memory(store) => {
            let now_mono = clock.now_monotonic();
            Ok(eval_dims_memory(
                store, algorithm, checks, now_mono, now_unix,
            ))
        }
        EngineBackend::Redis(redis) => redis
            .evaluate_many(&checks, now_unix)
            .map_err(|e| e.to_string()),
    }
}

/// Evaluate checks against the in-memory store.
fn eval_dims_memory(
    store: &MemoryStore,
    algorithm: crate::config::Algorithm,
    checks: Vec<(String, u64, u64)>,
    now_mono: crate::clock::Nanos,
    now_unix: i64,
) -> Vec<DimResult> {
    checks
        .into_iter()
        .map(|(key, limit_count, window_nanos)| {
            store.check_and_increment(
                &key,
                limit_count,
                window_nanos,
                algorithm,
                now_mono,
                now_unix,
            )
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Private helpers — dimension key building and dict construction
// ---------------------------------------------------------------------------

impl RateLimiterEngine {
    /// Build dimension checks from engine config.
    /// Mirrors Python `_build_rust_checks()` but runs in Rust.
    fn build_checks(
        &self,
        user: &str,
        tenant: Option<&str>,
        tool: &str,
    ) -> Vec<(String, u64, u64)> {
        let mut checks = Vec::with_capacity(3);
        if let Some(ref rl) = self.config.by_user {
            checks.push((format!("user:{}", user), rl.count, rl.window_nanos));
        }
        if let (Some(t), Some(rl)) = (tenant, &self.config.by_tenant) {
            checks.push((format!("tenant:{}", t), rl.count, rl.window_nanos));
        }
        // Tool names are normalised (lowercase) in EngineConfig at init time.
        // Defensive lowercase here to avoid silent mismatches if caller forgets.
        let tool_lower = tool.to_ascii_lowercase();
        if let Some(rl) = self.config.by_tool.get(&tool_lower) {
            checks.push((format!("tool:{}", tool_lower), rl.count, rl.window_nanos));
        }
        checks
    }
}

/// Build HTTP rate-limit headers dict — mirrors Python `_make_headers()`.
fn build_headers_dict<'py>(
    py: Python<'py>,
    eval: &EvalResult,
    include_retry_after: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let headers = PyDict::new(py);
    if eval.limit == u64::MAX {
        return Ok(headers);
    }
    headers.set_item("X-RateLimit-Limit", eval.limit.to_string())?;
    headers.set_item("X-RateLimit-Remaining", eval.remaining.to_string())?;
    headers.set_item("X-RateLimit-Reset", eval.reset_timestamp.to_string())?;
    if include_retry_after && let Some(retry) = eval.retry_after {
        headers.set_item("Retry-After", retry.to_string())?;
    }
    Ok(headers)
}

/// Build metadata dict — mirrors Python `_rust_to_plugin_meta()`.
fn build_meta_dict<'py>(
    py: Python<'py>,
    eval: &EvalResult,
    now_unix: i64,
) -> PyResult<Bound<'py, PyDict>> {
    let meta = PyDict::new(py);
    let reset_in = eval
        .retry_after
        .unwrap_or_else(|| (eval.reset_timestamp - now_unix).max(0));
    // "limited" means rate limits are configured, not that the request was blocked.
    meta.set_item("limited", true)?;
    meta.set_item("remaining", eval.remaining)?;
    meta.set_item("reset_in", reset_in)?;

    let has_violated = !eval.violated_dimensions.is_empty();
    let has_allowed = !eval.allowed_dimensions.is_empty();

    if has_violated || has_allowed {
        let dims = PyDict::new(py);
        if has_violated {
            let violated_list = PyList::empty(py);
            for dim in &eval.violated_dimensions {
                let d = PyDict::new(py);
                let dim_reset_in = dim
                    .retry_after
                    .unwrap_or_else(|| (dim.reset_timestamp - now_unix).max(0));
                d.set_item("limited", true)?;
                d.set_item("remaining", dim.remaining)?;
                d.set_item("reset_in", dim_reset_in)?;
                violated_list.append(d)?;
            }
            dims.set_item("violated", violated_list)?;
        }
        if has_allowed {
            let allowed_list = PyList::empty(py);
            for dim in &eval.allowed_dimensions {
                let d = PyDict::new(py);
                let dim_reset_in = (dim.reset_timestamp - now_unix).max(0);
                d.set_item("limited", true)?;
                d.set_item("remaining", dim.remaining)?;
                d.set_item("reset_in", dim_reset_in)?;
                allowed_list.append(d)?;
            }
            dims.set_item("allowed", allowed_list)?;
        }
        meta.set_item("dimensions", dims)?;
    }

    Ok(meta)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clock::FakeClock;
    use crate::config::Algorithm;

    fn init_python() {
        Python::initialize();
    }

    fn engine_with_fake_clock(
        by_user: Option<&str>,
        algorithm: Algorithm,
    ) -> (RateLimiterEngine, crate::clock::FakeClockHandle) {
        init_python();
        let (clock, handle) = FakeClock::new(1_000_000);
        let mut by_tool = HashMap::new();
        let cfg = EngineConfig {
            by_user: by_user.map(|s| crate::config::parse_rate(s).unwrap()),
            by_tenant: None,
            by_tool: {
                by_tool.insert(
                    "search".to_string(),
                    crate::config::parse_rate("5/m").unwrap(),
                );
                by_tool
            },
            algorithm,
        };
        let engine = RateLimiterEngine::new_with_clock(cfg, Arc::new(clock));
        (engine, handle)
    }

    // --- IFACE-01: config parsed at init ---

    #[test]
    fn config_parsed_at_init_by_tool_normalised() {
        let cfg = EngineConfig::new(
            Some("10/s"),
            None,
            {
                let mut m = HashMap::new();
                m.insert("Search".to_string(), "5/m".to_string());
                m
            },
            "fixed_window",
        )
        .unwrap();
        // Key must be lowercase
        assert!(cfg.by_tool.contains_key("search"));
        assert!(!cfg.by_tool.contains_key("Search"));
    }

    // --- IFACE-02: evaluate_many returns EvalResult ---

    #[test]
    fn evaluate_many_returns_eval_result_shape() {
        let (engine, handle) = engine_with_fake_clock(Some("10/s"), Algorithm::FixedWindow);
        let checks = vec![("user:alice".to_string(), 10, 1_000_000_000)];
        let result = engine.evaluate_many(checks, handle.unix_secs()).unwrap();
        // Shape: all fields present, first call always allowed
        assert!(result.allowed);
        assert_eq!(result.limit, 10);
        assert!(result.remaining > 0);
        assert!(result.retry_after.is_none());
    }

    // --- ARCH-01: evaluate_many is the only hot-path call ---
    // (Structural — enforced by the interface: Python has no other method to call)

    // --- CORR-03: reset_timestamp > now on allowed requests ---

    #[test]
    fn reset_timestamp_strictly_greater_than_now_on_allowed() {
        let (engine, handle) = engine_with_fake_clock(Some("10/s"), Algorithm::FixedWindow);
        let now_unix = handle.unix_secs();
        let checks = vec![("user:bob".to_string(), 10, 1_000_000_000)];
        let result = engine.evaluate_many(checks, now_unix).unwrap();
        assert!(result.allowed);
        assert!(
            result.reset_timestamp > now_unix,
            "reset_timestamp {} must be > now {}",
            result.reset_timestamp,
            now_unix
        );
    }

    // --- CORR-04: None tenant means no tenant check ---
    // (Structural — Python wrapper never adds a tenant check when tenant_id is None)

    // --- CORR-07: multi-dimension aggregation picks most restrictive ---

    #[test]
    fn evaluate_many_blocked_dimension_blocks_result() {
        let (engine, _handle) = engine_with_fake_clock(Some("2/s"), Algorithm::FixedWindow);
        // Exhaust the limit
        let checks = || vec![("user:carol".to_string(), 2, 1_000_000_000)];
        let _ = engine.evaluate_many(checks(), 1_000_000).unwrap(); // 1
        let _ = engine.evaluate_many(checks(), 1_000_000).unwrap(); // 2
        let result = engine.evaluate_many(checks(), 1_000_000).unwrap(); // 3 — must be blocked
        assert!(!result.allowed);
        assert_eq!(result.remaining, 0);
        assert!(result.retry_after.is_some());
    }

    #[test]
    fn evaluate_many_multiple_dims_picks_most_restrictive() {
        let (engine, _handle) = engine_with_fake_clock(None, Algorithm::FixedWindow);
        // user has 10/s, tenant has 2/s — after 2 requests tenant is exhausted
        let user_key = "user:dave".to_string();
        let tenant_key = "tenant:acme".to_string();
        let checks = || {
            vec![
                (user_key.clone(), 10, 1_000_000_000),
                (tenant_key.clone(), 2, 1_000_000_000),
            ]
        };
        let _ = engine.evaluate_many(checks(), 1_000_000).unwrap();
        let _ = engine.evaluate_many(checks(), 1_000_000).unwrap();
        let result = engine.evaluate_many(checks(), 1_000_000).unwrap();
        assert!(!result.allowed); // tenant exhausted → blocked
    }
}
