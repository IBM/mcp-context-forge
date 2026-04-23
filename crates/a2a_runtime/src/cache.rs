// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Two-layer cache: L1 DashMap (in-process) + L2 Redis.
//!
//! [`TieredCache`] provides `get`, `set`, `invalidate`, and `evict_l1`
//! operations.  L2 failures are always logged and swallowed — the cache
//! degrades gracefully when Redis is unavailable.
//!
//! [`RedisPool`] wraps a [`redis::aio::ConnectionManager`] (Arc-backed, cheap
//! to clone) and retains the original URL string so that [`CacheSubscriber`]
//! can open a dedicated pub/sub connection when needed.
//!
//! [`CacheSubscriber`] spawns a background Tokio task that subscribes to a
//! Redis pub/sub channel and calls user-supplied eviction callbacks on
//! invalidation messages.

use crate::eviction::evict_one_if_over_capacity;
use async_trait::async_trait;
use dashmap::DashMap;
use futures::StreamExt;
use redis::AsyncCommands;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::watch;
use tracing::{debug, warn};

// ---------------------------------------------------------------------------
// RedisPool
// ---------------------------------------------------------------------------

/// A shared Redis connection-pool wrapper.
///
/// Wraps a [`redis::aio::ConnectionManager`] (Arc-backed, cheap to clone) and
/// retains the original URL so that a dedicated pub/sub connection can be
/// opened later.
#[derive(Clone)]
pub struct RedisPool {
    manager: redis::aio::ConnectionManager,
    /// Original URL, kept for opening a separate pub/sub connection.
    url: Arc<String>,
}

impl RedisPool {
    /// Connect to Redis at `url`.
    ///
    /// Returns `None` on failure and logs a warning — callers should treat a
    /// missing pool as "L2 unavailable" rather than a fatal error.
    pub async fn connect(url: &str) -> Option<Self> {
        let client = match redis::Client::open(url) {
            Ok(c) => c,
            Err(e) => {
                warn!(url = url, error = %e, "redis: failed to build client");
                return None;
            }
        };
        match client.get_connection_manager().await {
            Ok(manager) => {
                debug!(url = url, "redis: connection manager ready");
                Some(Self {
                    manager,
                    url: Arc::new(url.to_owned()),
                })
            }
            Err(e) => {
                warn!(url = url, error = %e, "redis: could not connect, L2 cache disabled");
                None
            }
        }
    }

    /// Return a clone of the connection manager (O(1) — Arc-backed).
    pub fn conn(&self) -> redis::aio::ConnectionManager {
        self.manager.clone()
    }

    /// Return the original Redis URL string.
    pub fn raw_url(&self) -> &str {
        &self.url
    }
}

// ---------------------------------------------------------------------------
// L1 entry
// ---------------------------------------------------------------------------

/// A single L1 cache entry with an inline expiry timestamp.
struct L1Entry<T> {
    value: T,
    expires_at: Instant,
}

// ---------------------------------------------------------------------------
// TieredCache
// ---------------------------------------------------------------------------

#[async_trait]
trait CacheStorage: Send + Sync {
    async fn get(&self, key: &str) -> Result<Option<String>, String>;
    async fn set_ex(&self, key: &str, value: &str, ttl_secs: u64) -> Result<(), String>;
    async fn del(&self, key: &str) -> Result<(), String>;
}

struct RedisCacheStorage {
    redis: RedisPool,
}

#[async_trait]
impl CacheStorage for RedisCacheStorage {
    async fn get(&self, key: &str) -> Result<Option<String>, String> {
        let mut conn = self.redis.conn();
        conn.get(key).await.map_err(|e| e.to_string())
    }

    async fn set_ex(&self, key: &str, value: &str, ttl_secs: u64) -> Result<(), String> {
        let mut conn = self.redis.conn();
        conn.set_ex(key, value, ttl_secs)
            .await
            .map_err(|e| e.to_string())
    }

    async fn del(&self, key: &str) -> Result<(), String> {
        let mut conn = self.redis.conn();
        conn.del(key).await.map_err(|e| e.to_string())
    }
}

/// Generic two-layer cache: L1 [`DashMap`] + optional L2 Redis.
///
/// ## Type bounds
/// `T` must implement [`Clone`] (for L1 reads), [`Serialize`] (for L2 writes),
/// and [`DeserializeOwned`] (for L2 reads).
///
/// ## Eviction
/// L1 entries that have passed their TTL are treated as misses on read.
/// Before every L1 insert, [`crate::eviction::evict_one_if_over_capacity`] is
/// called to keep the map within the configured bound.
pub struct TieredCache<T> {
    l1: DashMap<String, L1Entry<T>>,
    l1_ttl: Duration,
    l1_max_entries: Option<usize>,
    storage: Option<Arc<dyn CacheStorage>>,
    l2_ttl_secs: u64,
    l2_key_prefix: String,
}

impl<T> TieredCache<T>
where
    T: Clone + Serialize + DeserializeOwned,
{
    /// Create a new [`TieredCache`].
    ///
    /// * `l1_ttl` — time-to-live for L1 entries.
    /// * `l1_max_entries` — maximum number of L1 entries; `None` means
    ///   unbounded.
    /// * `redis` — optional Redis pool for L2 storage.
    /// * `l2_ttl_secs` — TTL passed to Redis `SET EX`.
    /// * `l2_key_prefix` — prefix prepended to every Redis key.
    pub fn new(
        l1_ttl: Duration,
        l1_max_entries: Option<usize>,
        redis: Option<RedisPool>,
        l2_ttl_secs: u64,
        l2_key_prefix: impl Into<String>,
    ) -> Self {
        let storage =
            redis.map(|redis| Arc::new(RedisCacheStorage { redis }) as Arc<dyn CacheStorage>);
        Self::new_with_storage(l1_ttl, l1_max_entries, storage, l2_ttl_secs, l2_key_prefix)
    }

    fn new_with_storage(
        l1_ttl: Duration,
        l1_max_entries: Option<usize>,
        storage: Option<Arc<dyn CacheStorage>>,
        l2_ttl_secs: u64,
        l2_key_prefix: impl Into<String>,
    ) -> Self {
        Self {
            l1: DashMap::new(),
            l1_ttl,
            l1_max_entries,
            storage,
            l2_ttl_secs,
            l2_key_prefix: l2_key_prefix.into(),
        }
    }

    fn l2_key(&self, key: &str) -> String {
        format!("{}:{}", self.l2_key_prefix, key)
    }

    /// Look up `key`.
    ///
    /// 1. Check L1; return the value if present and not yet expired.
    /// 2. Check L2 (Redis); on hit, deserialise, promote to L1, and return.
    /// 3. Return `None` on a complete miss.
    pub async fn get(&self, key: &str) -> Option<T> {
        // --- L1 ---
        if let Some(entry) = self.l1.get(key) {
            if entry.expires_at > Instant::now() {
                debug!(key = key, "cache: L1 hit");
                return Some(entry.value.clone());
            }
            // Expired — drop the read guard before mutating.
            drop(entry);
            self.l1.remove(key);
        }

        // --- L2 ---
        if let Some(storage) = &self.storage {
            let l2_key = self.l2_key(key);
            match storage.get(&l2_key).await {
                Ok(Some(json)) => match serde_json::from_str::<T>(&json) {
                    Ok(value) => {
                        debug!(key = key, "cache: L2 hit, promoting to L1");
                        evict_one_if_over_capacity(&self.l1, self.l1_max_entries);
                        self.l1.insert(
                            key.to_owned(),
                            L1Entry {
                                value: value.clone(),
                                expires_at: Instant::now() + self.l1_ttl,
                            },
                        );
                        return Some(value);
                    }
                    Err(e) => {
                        warn!(key = key, error = %e, "cache: L2 JSON deserialise failed");
                    }
                },
                Ok(None) => {
                    debug!(key = key, "cache: L2 miss");
                }
                Err(e) => {
                    warn!(key = key, error = %e, "cache: L2 get failed");
                }
            }
        }

        None
    }

    /// Write `value` to both L1 and L2.
    ///
    /// L2 failures are logged and ignored — the L1 write always succeeds.
    pub async fn set(&self, key: &str, value: T) {
        // --- L1 ---
        evict_one_if_over_capacity(&self.l1, self.l1_max_entries);
        self.l1.insert(
            key.to_owned(),
            L1Entry {
                value: value.clone(),
                expires_at: Instant::now() + self.l1_ttl,
            },
        );

        // --- L2 ---
        if let Some(storage) = &self.storage {
            match serde_json::to_string(&value) {
                Ok(json) => {
                    let l2_key = self.l2_key(key);
                    if let Err(e) = storage.set_ex(&l2_key, &json, self.l2_ttl_secs).await {
                        warn!(key = key, error = %e, "cache: L2 set_ex failed");
                    }
                }
                Err(e) => {
                    warn!(key = key, error = %e, "cache: JSON serialise failed, L2 write skipped");
                }
            }
        }
    }

    /// Remove `key` from both L1 and L2.
    ///
    /// L2 failures are logged and ignored.
    pub async fn invalidate(&self, key: &str) {
        self.l1.remove(key);

        if let Some(storage) = &self.storage {
            let l2_key = self.l2_key(key);
            if let Err(e) = storage.del(&l2_key).await {
                warn!(key = key, error = %e, "cache: L2 del failed");
            }
        }
    }

    /// Remove `key` from L1 only.
    ///
    /// Intended for use by the pub/sub subscriber after receiving an
    /// invalidation message — the subscriber does not hold an owned reference
    /// to the cache, so L2 cleanup is handled separately.
    pub fn evict_l1(&self, key: &str) {
        self.l1.remove(key);
    }
}

// ---------------------------------------------------------------------------
// Invalidation message
// ---------------------------------------------------------------------------

/// Structured pub/sub invalidation payload.
///
/// Serialised as a tagged enum:
/// - `{"type":"agent","name":"my-agent"}`
/// - `{"type":"task","task_id":"abc-123"}`
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum InvalidationMessage {
    Agent { name: String },
    Task { task_id: String },
}

// ---------------------------------------------------------------------------
// CacheSubscriber
// ---------------------------------------------------------------------------

/// Background Tokio task that subscribes to a Redis pub/sub channel and
/// evicts matching L1 entries on invalidation messages.
pub struct CacheSubscriber;

impl CacheSubscriber {
    /// Spawn the subscriber task.
    ///
    /// * `redis_pool` — pool used to obtain a dedicated pub/sub connection.
    /// * `channel` — Redis channel name to subscribe to.
    /// * `agent_cache_evict` — closure called with the agent name when an
    ///   `Agent` invalidation message arrives.
    ///
    /// Returns a [`watch::Sender<()>`].  Dropping the sender (or calling
    /// [`watch::Sender::send`]) causes the subscriber task to stop gracefully.
    pub fn spawn(
        redis_pool: RedisPool,
        channel: String,
        agent_cache_evict: Arc<dyn Fn(&str) + Send + Sync>,
    ) -> watch::Sender<()> {
        let (tx, mut rx) = watch::channel(());

        tokio::spawn(async move {
            // Open a fresh client for pub/sub — connection managers are not
            // suitable for pub/sub because they multiplex on a shared
            // connection.
            let client = match redis::Client::open(redis_pool.raw_url()) {
                Ok(c) => c,
                Err(e) => {
                    warn!(channel = %channel, error = %e, "cache subscriber: failed to build redis client");
                    return;
                }
            };

            let mut pubsub = match client.get_async_pubsub().await {
                Ok(ps) => ps,
                Err(e) => {
                    warn!(channel = %channel, error = %e, "cache subscriber: pubsub connect failed");
                    return;
                }
            };

            if let Err(e) = pubsub.subscribe(&channel).await {
                warn!(channel = %channel, error = %e, "cache subscriber: subscribe failed");
                return;
            }

            debug!(channel = %channel, "cache subscriber: listening");

            let mut stream = pubsub.on_message();
            loop {
                tokio::select! {
                    msg = stream.next() => {
                        let msg = match msg {
                            Some(m) => m,
                            None => {
                                warn!(channel = %channel, "cache subscriber: stream ended");
                                break;
                            }
                        };
                        let payload: String = match msg.get_payload() {
                            Ok(p) => p,
                            Err(e) => {
                                warn!(channel = %channel, error = %e, "cache subscriber: bad payload");
                                continue;
                            }
                        };
                        handle_invalidation_payload(&payload, &agent_cache_evict);
                    }
                    _ = rx.changed() => {
                        debug!(channel = %channel, "cache subscriber: shutdown signal received");
                        break;
                    }
                }
            }
        });

        tx
    }
}

fn handle_invalidation_payload(payload: &str, agent_cache_evict: &Arc<dyn Fn(&str) + Send + Sync>) {
    match serde_json::from_str::<InvalidationMessage>(payload) {
        Ok(InvalidationMessage::Agent { name }) => {
            debug!(agent = %name, "cache subscriber: evicting agent");
            agent_cache_evict(&name);
        }
        Ok(InvalidationMessage::Task { task_id }) => {
            debug!(task_id = %task_id, "cache subscriber: task invalidation (no-op L1)");
        }
        Err(e) => {
            warn!(payload = %payload, error = %e, "cache subscriber: unknown message");
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Mutex;

    #[derive(Default)]
    struct FakeCacheStorage {
        values: Mutex<HashMap<String, String>>,
        fail_get: Mutex<bool>,
        fail_set: Mutex<bool>,
        fail_del: Mutex<bool>,
    }

    #[async_trait]
    impl CacheStorage for FakeCacheStorage {
        async fn get(&self, key: &str) -> Result<Option<String>, String> {
            if *self.fail_get.lock().unwrap() {
                return Err("get failed".to_string());
            }
            Ok(self.values.lock().unwrap().get(key).cloned())
        }

        async fn set_ex(&self, key: &str, value: &str, _ttl_secs: u64) -> Result<(), String> {
            if *self.fail_set.lock().unwrap() {
                return Err("set failed".to_string());
            }
            self.values
                .lock()
                .unwrap()
                .insert(key.to_string(), value.to_string());
            Ok(())
        }

        async fn del(&self, key: &str) -> Result<(), String> {
            if *self.fail_del.lock().unwrap() {
                return Err("del failed".to_string());
            }
            self.values.lock().unwrap().remove(key);
            Ok(())
        }
    }

    // -- InvalidationMessage deserialisation ---------------------------------

    #[test]
    fn invalidation_message_deserializes_agent() {
        let json = r#"{"type":"agent","name":"my-agent"}"#;
        let msg: InvalidationMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(
            msg,
            InvalidationMessage::Agent { ref name } if name == "my-agent"
        ));
    }

    #[test]
    fn invalidation_message_deserializes_task() {
        let json = r#"{"type":"task","task_id":"abc-123"}"#;
        let msg: InvalidationMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(
            msg,
            InvalidationMessage::Task { ref task_id } if task_id == "abc-123"
        ));
    }

    // -- TieredCache (L1 only, no Redis) ------------------------------------

    fn make_cache() -> TieredCache<String> {
        TieredCache::new(Duration::from_secs(60), Some(100), None, 300, "test")
    }

    #[tokio::test]
    async fn tiered_cache_l1_hit() {
        let cache = make_cache();
        cache.set("foo", "bar".to_string()).await;
        let got = cache.get("foo").await;
        assert_eq!(got.as_deref(), Some("bar"));
    }

    #[tokio::test]
    async fn tiered_cache_l1_miss_returns_none_without_redis() {
        let cache = make_cache();
        let got = cache.get("nonexistent").await;
        assert!(got.is_none());
    }

    #[tokio::test]
    async fn tiered_cache_invalidate_removes_from_l1() {
        let cache = make_cache();
        cache.set("key", "value".to_string()).await;
        assert!(cache.get("key").await.is_some());
        cache.invalidate("key").await;
        assert!(cache.get("key").await.is_none());
    }

    #[tokio::test]
    async fn tiered_cache_expired_entry_returns_none() {
        let cache: TieredCache<String> =
            TieredCache::new(Duration::from_millis(1), Some(100), None, 300, "test");
        cache.set("expiring", "soon".to_string()).await;
        // Give the entry time to expire.
        tokio::time::sleep(Duration::from_millis(10)).await;
        let got = cache.get("expiring").await;
        assert!(got.is_none());
    }

    #[tokio::test]
    async fn tiered_cache_reads_writes_and_invalidates_l2_storage() {
        let storage = Arc::new(FakeCacheStorage::default());
        storage
            .values
            .lock()
            .unwrap()
            .insert("test:l2-key".to_string(), "\"from-l2\"".to_string());
        let cache = TieredCache::new_with_storage(
            Duration::from_secs(60),
            Some(100),
            Some(storage.clone()),
            300,
            "test",
        );

        assert_eq!(cache.get("l2-key").await.as_deref(), Some("from-l2"));
        cache.set("new-key", "new-value".to_string()).await;
        assert_eq!(
            storage.values.lock().unwrap().get("test:new-key"),
            Some(&"\"new-value\"".to_string())
        );
        cache.invalidate("new-key").await;
        assert!(!storage.values.lock().unwrap().contains_key("test:new-key"));
    }

    #[tokio::test]
    async fn tiered_cache_handles_l2_bad_json_and_storage_errors() {
        let storage = Arc::new(FakeCacheStorage::default());
        storage
            .values
            .lock()
            .unwrap()
            .insert("test:bad-json".to_string(), "{not-json".to_string());
        let cache = TieredCache::new_with_storage(
            Duration::from_secs(60),
            Some(100),
            Some(storage.clone()),
            300,
            "test",
        );
        assert!(cache.get("bad-json").await.is_none());

        *storage.fail_get.lock().unwrap() = true;
        assert!(cache.get("error").await.is_none());
        *storage.fail_get.lock().unwrap() = false;

        *storage.fail_set.lock().unwrap() = true;
        cache.set("set-error", "value".to_string()).await;
        *storage.fail_set.lock().unwrap() = false;

        *storage.fail_del.lock().unwrap() = true;
        cache.invalidate("del-error").await;
    }

    #[test]
    fn evict_l1_removes_only_local_entry() {
        let cache = make_cache();
        cache.l1.insert(
            "evict-me".to_string(),
            L1Entry {
                value: "value".to_string(),
                expires_at: Instant::now() + Duration::from_secs(60),
            },
        );
        cache.evict_l1("evict-me");
        assert!(!cache.l1.contains_key("evict-me"));
    }

    #[tokio::test]
    async fn redis_pool_connect_returns_none_for_invalid_urls() {
        assert!(RedisPool::connect("not-a-redis-url").await.is_none());
    }

    #[test]
    fn handle_invalidation_payload_processes_agent_task_and_unknown_messages() {
        let evicted = Arc::new(Mutex::new(Vec::<String>::new()));
        let evicted_ref = Arc::clone(&evicted);
        let callback: Arc<dyn Fn(&str) + Send + Sync> = Arc::new(move |key: &str| {
            evicted_ref.lock().unwrap().push(key.to_string());
        });

        handle_invalidation_payload(r#"{"type":"agent","name":"agent-1"}"#, &callback);
        handle_invalidation_payload(r#"{"type":"task","task_id":"task-1"}"#, &callback);
        handle_invalidation_payload("not-json", &callback);

        assert_eq!(evicted.lock().unwrap().as_slice(), ["agent-1"]);
    }
}
