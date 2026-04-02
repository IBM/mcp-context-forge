// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Redis backend for the rate limiter engine.
//
// Holds a lazily-created multiplexed async Redis connection.
// Fires the same batch Lua scripts as the Python RedisBackend — one call per
// evaluate_many() invocation regardless of dimension count (REDIS-01/03).
// Uses EVALSHA with NOSCRIPT fallback to EVAL (REDIS-02).
//
// Key format: `{prefix}:{dimension_key}:{window_seconds}`
// This matches the Python RedisBackend key format exactly so that instances
// running the Rust backend and instances running the Python fallback share the
// same Redis counters during a rolling upgrade.

use std::cmp::max;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};

use parking_lot::Mutex;
use redis::aio::MultiplexedConnection;
use tokio::runtime::{Builder, Handle, Runtime};

use crate::config::Algorithm;
use crate::types::DimResult;

// ---------------------------------------------------------------------------
// Batch Lua scripts — identical to Python RedisBackend._LUA_BATCH_* constants
//
// INVARIANT (rolling-upgrade compatibility):
//   These scripts and the key format ({prefix}:{dimension_key}:{window_seconds})
//   MUST stay in sync with the Python RedisBackend in
//   plugins/rate_limiter/rate_limiter.py.  Both implementations share the same
//   Redis counters so that mixed Rust/Python deployments enforce a single set
//   of limits during a rolling upgrade.
//
//   If you change a script or the key format here, update the Python copy and
//   validate with the test_redis_key_format_parity_* tests.
//
//   LIMITATION: The Rust path derives `now_float` from `now_unix as f64`
//   (whole-second precision) while the Python path passes raw `time.time()`
//   (sub-second precision).  During a mixed rolling upgrade, sorted-set
//   members will have different precision levels for the same logical
//   timestamp.  The functional impact is at most 1 second on response
//   headers — rate enforcement correctness is unaffected.
// ---------------------------------------------------------------------------
//
// LIMITATION: Batch scripts pass multiple KEYS (one per dimension) in a
// single EVAL/EVALSHA call.  In Redis Cluster, all keys must hash to the
// same slot.  The key format `{prefix}:{dim}:{window}` does NOT use hash
// tags, so these scripts will fail on Redis Cluster.  Use standalone Redis
// or Sentinel for multi-dimension batch evaluation.
// ---------------------------------------------------------------------------

const LUA_BATCH_FIXED: &str = r#"
local results = {}
for i = 1, #KEYS do
    local current = redis.call('INCR', KEYS[i])
    if current == 1 then
        redis.call('EXPIRE', KEYS[i], ARGV[i])
    end
    local ttl = redis.call('TTL', KEYS[i])
    results[i] = {current, ttl}
end
return results
"#;

const LUA_BATCH_SLIDING: &str = r#"
local now = tonumber(ARGV[1])
local results = {}
for i = 1, #KEYS do
    local base = 1 + (i-1)*3 + 1
    local window = tonumber(ARGV[base])
    local limit  = tonumber(ARGV[base+1])
    local member = ARGV[base+2]
    local cutoff = now - window
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', cutoff)
    local count = tonumber(redis.call('ZCARD', KEYS[i]))
    redis.call('EXPIRE', KEYS[i], window + 1)
    if count >= limit then
        local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        local oldest_ts = 0
        if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
        results[i] = {0, count, oldest_ts}
    else
        redis.call('ZADD', KEYS[i], now, member)
        count = count + 1
        local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        local oldest_ts = 0
        if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
        results[i] = {1, count, oldest_ts}
    end
end
return results
"#;

// NOTE: Lua uses floating-point arithmetic for token refill (tokens + elapsed * rate),
// while the in-memory Rust backend uses integer milli-token math (u128).  Under sustained
// high-frequency traffic the two may diverge by ±1 token due to float precision loss.
// This is acceptable for rate limiting — the behavioral contract is identical.
const LUA_BATCH_TOKEN_BUCKET: &str = r#"
local now = tonumber(ARGV[1])
local results = {}
for i = 1, #KEYS do
    local base = 1 + (i-1)*2 + 1
    local capacity = tonumber(ARGV[base])
    local rate = tonumber(ARGV[base+1])
    local data = redis.call('HMGET', KEYS[i], 'tokens', 'last_refill')
    local tokens = tonumber(data[1])
    local last_refill = tonumber(data[2])
    if tokens == nil then
        tokens = capacity - 1
        redis.call('HSET', KEYS[i], 'tokens', tokens, 'last_refill', now)
        local ttl = math.ceil(capacity / rate) + 1
        redis.call('EXPIRE', KEYS[i], ttl)
        results[i] = {1, math.floor(tokens), 0}
    else
        local elapsed = now - last_refill
        tokens = math.min(capacity, tokens + elapsed * rate)
        local allowed, time_to_next
        if tokens >= 1.0 then
            tokens = tokens - 1.0
            allowed = 1
            time_to_next = 0
        else
            allowed = 0
            time_to_next = math.ceil((1.0 - tokens) / rate)
        end
        redis.call('HSET', KEYS[i], 'tokens', tokens, 'last_refill', now)
        local ttl = math.ceil((capacity - tokens) / rate) + 1
        redis.call('EXPIRE', KEYS[i], ttl)
        results[i] = {allowed, math.floor(tokens), time_to_next}
    end
end
return results
"#;

// ---------------------------------------------------------------------------
// Unique member counter for sliding window sorted sets
// ---------------------------------------------------------------------------

static MEMBER_CTR: AtomicU64 = AtomicU64::new(0);

/// Process-unique PID, cached once.
fn process_id() -> u32 {
    static PID: OnceLock<u32> = OnceLock::new();
    *PID.get_or_init(std::process::id)
}

/// Random nonce generated once at process start.  Combined with PID and atomic
/// counter this guarantees unique sorted-set members across gateway replicas
/// even in containerized environments where PID 1 is common, preventing ZADD
/// overwrites that would cause undercounting.
fn instance_nonce() -> u64 {
    static NONCE: OnceLock<u64> = OnceLock::new();
    *NONCE.get_or_init(|| {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let mut h = DefaultHasher::new();
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
            .hash(&mut h);
        std::process::id().hash(&mut h);
        h.finish()
    })
}

fn unique_member(now: f64) -> String {
    use std::fmt::Write;
    let n = MEMBER_CTR.fetch_add(1, Ordering::Relaxed);
    let mut buf = String::with_capacity(60);
    let _ = write!(
        buf,
        "{:.6}:{}:{}:{}",
        now,
        process_id(),
        instance_nonce(),
        n
    );
    buf
}

// ---------------------------------------------------------------------------
// Value extraction helpers
// ---------------------------------------------------------------------------

fn val_i64(v: &redis::Value) -> i64 {
    match v {
        redis::Value::Int(i) => *i,
        redis::Value::BulkString(b) => std::str::from_utf8(b)
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or_else(|| {
                log::error!("Redis returned unparseable i64 BulkString; defaulting to 0");
                0
            }),
        other => {
            log::error!(
                "Redis returned unexpected value type for i64: {:?}; defaulting to 0",
                other
            );
            0
        }
    }
}

fn val_f64(v: &redis::Value) -> f64 {
    match v {
        redis::Value::Int(i) => *i as f64,
        redis::Value::BulkString(b) => std::str::from_utf8(b)
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or_else(|| {
                log::error!("Redis returned unparseable f64 BulkString; defaulting to 0.0");
                0.0
            }),
        other => {
            log::error!(
                "Redis returned unexpected value type for f64: {:?}; defaulting to 0.0",
                other
            );
            0.0
        }
    }
}

fn inner_array(outer: &redis::Value, i: usize) -> Option<&Vec<redis::Value>> {
    match outer {
        redis::Value::Array(a) => match a.get(i) {
            Some(redis::Value::Array(inner)) => Some(inner),
            _ => None,
        },
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// RedisRateLimiter
// ---------------------------------------------------------------------------

pub struct RedisRateLimiter {
    client: redis::Client,
    conn: Mutex<Option<MultiplexedConnection>>,
    algorithm: Algorithm,
    prefix: String,
    /// Cached SHA for the active algorithm's batch Lua script (REDIS-02).
    /// Populated on first use via SCRIPT LOAD; cleared on connection reset.
    script_sha: Mutex<Option<String>>,
}

fn shared_runtime() -> Result<&'static Runtime, redis::RedisError> {
    static RUNTIME: OnceLock<Result<Runtime, String>> = OnceLock::new();
    let result = RUNTIME.get_or_init(|| {
        Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .map_err(|e| e.to_string())
    });
    match result {
        Ok(rt) => Ok(rt),
        Err(msg) => Err(redis::RedisError::from((
            redis::ErrorKind::IoError,
            "tokio runtime init failed",
            msg.clone(),
        ))),
    }
}

impl RedisRateLimiter {
    pub fn new(
        redis_url: &str,
        algorithm: Algorithm,
        prefix: String,
    ) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        Ok(Self {
            client,
            conn: Mutex::new(None),
            algorithm,
            prefix,
            script_sha: Mutex::new(None),
        })
    }

    async fn connection_async(&self) -> Result<MultiplexedConnection, redis::RedisError> {
        {
            let conn_guard = self.conn.lock();
            if let Some(conn) = conn_guard.as_ref() {
                return Ok(conn.clone());
            }
        }

        // Timeout prevents blocking the gateway thread indefinitely when
        // Redis is unreachable (network partition, DNS failure, etc.).
        let conn = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            self.client.get_multiplexed_tokio_connection(),
        )
        .await
        .map_err(|_| {
            redis::RedisError::from((
                redis::ErrorKind::IoError,
                "Redis connection timed out after 5 s",
            ))
        })??;

        let mut conn_guard = self.conn.lock();
        if let Some(existing) = conn_guard.as_ref() {
            return Ok(existing.clone());
        }
        *conn_guard = Some(conn.clone());
        Ok(conn)
    }

    fn reset_connection(&self) {
        log::warn!("Redis connection reset after error; will reconnect on next request");
        *self.conn.lock() = None;
        *self.script_sha.lock() = None;
    }

    /// Return the batch Lua script for the active algorithm.
    fn batch_script(&self) -> &'static str {
        match self.algorithm {
            Algorithm::FixedWindow => LUA_BATCH_FIXED,
            Algorithm::SlidingWindow => LUA_BATCH_SLIDING,
            Algorithm::TokenBucket => LUA_BATCH_TOKEN_BUCKET,
        }
    }

    /// REDIS-02: Load the active algorithm's script via SCRIPT LOAD and cache
    /// the SHA.  Returns the cached SHA on subsequent calls.
    async fn ensure_script_loaded(
        &self,
        conn: &mut MultiplexedConnection,
    ) -> Result<String, redis::RedisError> {
        {
            let guard = self.script_sha.lock();
            if let Some(sha) = guard.as_ref() {
                return Ok(sha.clone());
            }
        }
        let sha: String = redis::cmd("SCRIPT")
            .arg("LOAD")
            .arg(self.batch_script())
            .query_async(conn)
            .await?;
        *self.script_sha.lock() = Some(sha.clone());
        Ok(sha)
    }

    /// REDIS-02: Execute via EVALSHA when the SHA is cached; fall back to EVAL
    /// on NOSCRIPT (Redis restarted and flushed its script cache).
    async fn evalsha_or_eval(
        &self,
        conn: &mut MultiplexedConnection,
        num_keys: usize,
        keys: &[String],
        args: &[Vec<u8>],
    ) -> Result<redis::Value, redis::RedisError> {
        // Try EVALSHA if we have a cached SHA.
        if let Ok(sha) = self.ensure_script_loaded(conn).await {
            let mut cmd = redis::cmd("EVALSHA");
            cmd.arg(&sha).arg(num_keys);
            for k in keys {
                cmd.arg(k.as_bytes());
            }
            for a in args {
                cmd.arg(a.as_slice());
            }
            match cmd.query_async::<redis::Value>(conn).await {
                Ok(val) => return Ok(val),
                Err(e) if e.kind() == redis::ErrorKind::NoScriptError => {
                    // NOSCRIPT — clear cached SHA, fall through to EVAL.
                    *self.script_sha.lock() = None;
                }
                Err(e) => return Err(e),
            }
        }

        // Fallback: full EVAL (first call or after NOSCRIPT).
        let mut cmd = redis::cmd("EVAL");
        cmd.arg(self.batch_script()).arg(num_keys);
        for k in keys {
            cmd.arg(k.as_bytes());
        }
        for a in args {
            cmd.arg(a.as_slice());
        }
        let result: redis::Value = cmd.query_async(conn).await?;

        // Re-cache SHA for next call.
        let _ = self.ensure_script_loaded(conn).await;

        Ok(result)
    }

    /// Evaluate all dimension checks in a single Redis call.
    ///
    /// `checks` is `(dimension_key, limit_count, window_nanos)` — same shape
    /// as the memory engine.  Returns one `DimResult` per check.
    pub fn evaluate_many(
        &self,
        checks: &[(String, u64, u64)],
        now_unix: i64,
    ) -> Result<Vec<DimResult>, redis::RedisError> {
        // Guard: block_on from within an existing Tokio runtime panics.
        // Return a clear error instead of crashing the Python process.
        if Handle::try_current().is_ok() {
            return Err(redis::RedisError::from((
                redis::ErrorKind::IoError,
                "evaluate_many (sync) called from within a Tokio runtime; use evaluate_many_async instead",
            )));
        }
        shared_runtime()?.block_on(self.evaluate_many_async(checks, now_unix))
    }

    pub async fn evaluate_many_async(
        &self,
        checks: &[(String, u64, u64)],
        now_unix: i64,
    ) -> Result<Vec<DimResult>, redis::RedisError> {
        if checks.is_empty() {
            return Ok(vec![]);
        }

        // Derive from the passed-in now_unix so Python time mocks propagate
        // to Redis Lua scripts (CORR-02).
        let now_float = now_unix as f64;

        let mut conn = self.connection_async().await?;
        let result = match self.algorithm {
            Algorithm::FixedWindow => self.eval_fixed(&mut conn, checks, now_unix).await,
            Algorithm::SlidingWindow => {
                self.eval_sliding(&mut conn, checks, now_float, now_unix)
                    .await
            }
            Algorithm::TokenBucket => {
                self.eval_token_bucket(&mut conn, checks, now_float, now_unix)
                    .await
            }
        };
        if let Err(ref e) = result {
            // Only reset the multiplexed connection on transport-level errors.
            // Script/type errors are recoverable without dropping in-flight requests.
            if matches!(
                e.kind(),
                redis::ErrorKind::IoError
                    | redis::ErrorKind::BusyLoadingError
                    | redis::ErrorKind::TryAgain
            ) {
                self.reset_connection();
            }
        }
        result
    }

    fn redis_key(&self, dim_key: &str, window_nanos: u64) -> String {
        let window_secs = (window_nanos / 1_000_000_000).max(1);
        format!("{}:{}:{}", self.prefix, dim_key, window_secs)
    }

    fn token_bucket_time_to_full(limit: u64, remaining: u64, window_nanos: u64) -> i64 {
        if remaining >= limit {
            return 0;
        }
        let window_secs = window_nanos as f64 / 1_000_000_000.0;
        let refill_rate = limit as f64 / window_secs;
        let tokens_needed = limit - remaining;
        max(1, (tokens_needed as f64 / refill_rate) as i64)
    }

    // --- Fixed window ---

    async fn eval_fixed(
        &self,
        conn: &mut MultiplexedConnection,
        checks: &[(String, u64, u64)],
        now_unix: i64,
    ) -> Result<Vec<DimResult>, redis::RedisError> {
        let keys: Vec<String> = checks
            .iter()
            .map(|(k, _, w)| self.redis_key(k, *w))
            .collect();
        let args: Vec<Vec<u8>> = checks
            .iter()
            .map(|(_, _, w)| format!("{}", (w / 1_000_000_000).max(1)).into_bytes())
            .collect();

        let raw = self.evalsha_or_eval(conn, keys.len(), &keys, &args).await?;
        let mut results = Vec::with_capacity(checks.len());

        for (i, (_, limit, _)) in checks.iter().enumerate() {
            let inner = inner_array(&raw, i).ok_or_else(|| {
                redis::RedisError::from((redis::ErrorKind::TypeError, "expected inner array"))
            })?;
            let count = val_i64(inner.first().unwrap_or(&redis::Value::Int(0))) as u64;
            let ttl = val_i64(inner.get(1).unwrap_or(&redis::Value::Int(0)));
            let reset_timestamp = now_unix + ttl.max(0);

            if count > *limit {
                results.push(DimResult {
                    allowed: false,
                    limit: *limit,
                    remaining: 0,
                    reset_timestamp,
                    retry_after: Some(ttl.max(1)),
                });
            } else {
                results.push(DimResult {
                    allowed: true,
                    limit: *limit,
                    remaining: limit - count,
                    reset_timestamp,
                    retry_after: None,
                });
            }
        }
        Ok(results)
    }

    // --- Sliding window ---

    async fn eval_sliding(
        &self,
        conn: &mut MultiplexedConnection,
        checks: &[(String, u64, u64)],
        now_float: f64,
        now_unix: i64,
    ) -> Result<Vec<DimResult>, redis::RedisError> {
        let keys: Vec<String> = checks
            .iter()
            .map(|(k, _, w)| self.redis_key(k, *w))
            .collect();

        let mut args: Vec<Vec<u8>> = vec![format!("{}", now_float).into_bytes()];
        for (_, limit, window_nanos) in checks {
            let window_secs = (window_nanos / 1_000_000_000).max(1);
            args.push(format!("{}", window_secs).into_bytes());
            args.push(format!("{}", limit).into_bytes());
            args.push(unique_member(now_float).into_bytes());
        }

        let raw = self.evalsha_or_eval(conn, keys.len(), &keys, &args).await?;
        let mut results = Vec::with_capacity(checks.len());

        for (i, (_, limit, window_nanos)) in checks.iter().enumerate() {
            let inner = inner_array(&raw, i).ok_or_else(|| {
                redis::RedisError::from((redis::ErrorKind::TypeError, "expected inner array"))
            })?;
            let allowed_int = val_i64(inner.first().unwrap_or(&redis::Value::Int(0)));
            let count = val_i64(inner.get(1).unwrap_or(&redis::Value::Int(0))) as u64;
            let oldest_ts = val_f64(inner.get(2).unwrap_or(&redis::Value::Int(0)));
            let window_secs = (window_nanos / 1_000_000_000) as f64;
            let reset_timestamp = (oldest_ts + window_secs) as i64;
            let reset_in = (reset_timestamp - now_unix).max(1);

            if allowed_int == 0 {
                results.push(DimResult {
                    allowed: false,
                    limit: *limit,
                    remaining: 0,
                    reset_timestamp,
                    retry_after: Some(reset_in),
                });
            } else {
                results.push(DimResult {
                    allowed: true,
                    limit: *limit,
                    remaining: limit.saturating_sub(count),
                    reset_timestamp,
                    retry_after: None,
                });
            }
        }
        Ok(results)
    }

    // --- Token bucket ---

    async fn eval_token_bucket(
        &self,
        conn: &mut MultiplexedConnection,
        checks: &[(String, u64, u64)],
        now_float: f64,
        now_unix: i64,
    ) -> Result<Vec<DimResult>, redis::RedisError> {
        let keys: Vec<String> = checks
            .iter()
            .map(|(k, _, w)| self.redis_key(k, *w))
            .collect();

        let mut args: Vec<Vec<u8>> = vec![format!("{}", now_float).into_bytes()];
        for (_, limit, window_nanos) in checks {
            let window_secs = *window_nanos as f64 / 1_000_000_000.0;
            let rate = *limit as f64 / window_secs;
            args.push(format!("{}", limit).into_bytes());
            args.push(format!("{}", rate).into_bytes());
        }

        let raw = self.evalsha_or_eval(conn, keys.len(), &keys, &args).await?;
        let mut results = Vec::with_capacity(checks.len());

        for (i, (_, limit, window_nanos)) in checks.iter().enumerate() {
            let inner = inner_array(&raw, i).ok_or_else(|| {
                redis::RedisError::from((redis::ErrorKind::TypeError, "expected inner array"))
            })?;
            let allowed_int = val_i64(inner.first().unwrap_or(&redis::Value::Int(0)));
            let remaining = val_i64(inner.get(1).unwrap_or(&redis::Value::Int(0))) as u64;
            let time_to_next = val_i64(inner.get(2).unwrap_or(&redis::Value::Int(0)));

            if allowed_int == 0 {
                let reset_timestamp = now_unix + time_to_next.max(1);
                results.push(DimResult {
                    allowed: false,
                    limit: *limit,
                    remaining: 0,
                    reset_timestamp,
                    retry_after: Some(time_to_next.max(1)),
                });
            } else {
                let time_to_full =
                    Self::token_bucket_time_to_full(*limit, remaining, *window_nanos);
                let reset_timestamp = now_unix + time_to_full;
                results.push(DimResult {
                    allowed: true,
                    limit: *limit,
                    remaining,
                    reset_timestamp,
                    retry_after: None,
                });
            }
        }
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::RedisRateLimiter;

    #[test]
    fn token_bucket_success_reset_uses_time_to_full() {
        let window_nanos = 10_000_000_000_u64; // 10s
        let limit = 10_u64;
        let remaining = 9_u64;
        assert_eq!(
            RedisRateLimiter::token_bucket_time_to_full(limit, remaining, window_nanos),
            1
        );

        let remaining = 5_u64;
        assert_eq!(
            RedisRateLimiter::token_bucket_time_to_full(limit, remaining, window_nanos),
            5
        );
    }
}
