// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Redis-backed session management for A2A authenticated streams.
//!
//! A [`SessionRecord`] binds an authenticated identity to a fingerprint of
//! the client's auth headers.  [`SessionManager`] stores session records in
//! Redis under the key `mcpgw:a2a:session:{session_id}` with a configurable
//! TTL that can be refreshed on activity.

use crate::cache::RedisPool;
use async_trait::async_trait;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tracing::{debug, warn};
use uuid::Uuid;

// ---------------------------------------------------------------------------
// SessionRecord
// ---------------------------------------------------------------------------

/// A single persisted session entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionRecord {
    /// Authenticated identity context (e.g. JWT claims).
    pub auth_context: Value,
    /// SHA-256 fingerprint of the client's auth headers at session creation.
    pub auth_fingerprint: String,
    /// ID of the worker instance that created the session.
    pub worker_id: String,
    /// Unix epoch milliseconds when the session was created.
    pub created_at_ms: u64,
    /// Unix epoch milliseconds when the session was last accessed.
    pub last_active_at_ms: u64,
}

impl SessionRecord {
    /// Return `true` if `fingerprint` matches the stored auth fingerprint.
    pub fn matches_fingerprint(&self, fingerprint: &str) -> bool {
        self.auth_fingerprint == fingerprint
    }
}

// ---------------------------------------------------------------------------
// SessionManager
// ---------------------------------------------------------------------------

/// Redis-backed session manager.
///
/// Each [`SessionManager`] instance is associated with a specific worker UUID
/// so that distributed deployments can trace which node created a session.
#[async_trait]
trait SessionStorage: Send + Sync {
    async fn set_ex(&self, key: &str, value: &str, ttl_secs: u64) -> Result<(), String>;
    async fn get(&self, key: &str) -> Result<Option<String>, String>;
    async fn expire(&self, key: &str, ttl_secs: u64) -> Result<bool, String>;
    async fn del(&self, key: &str) -> Result<u32, String>;
}

struct RedisSessionStorage {
    redis: RedisPool,
}

struct MemorySessionStorage {
    values: std::sync::Mutex<HashMap<String, String>>,
}

impl Default for MemorySessionStorage {
    fn default() -> Self {
        Self {
            values: std::sync::Mutex::new(HashMap::new()),
        }
    }
}

#[async_trait]
impl SessionStorage for RedisSessionStorage {
    async fn set_ex(&self, key: &str, value: &str, ttl_secs: u64) -> Result<(), String> {
        let mut conn = self.redis.conn();
        conn.set_ex(key, value, ttl_secs)
            .await
            .map_err(|e| e.to_string())
    }

    async fn get(&self, key: &str) -> Result<Option<String>, String> {
        let mut conn = self.redis.conn();
        conn.get(key).await.map_err(|e| e.to_string())
    }

    async fn expire(&self, key: &str, ttl_secs: u64) -> Result<bool, String> {
        let mut conn = self.redis.conn();
        conn.expire(key, ttl_secs as i64)
            .await
            .map_err(|e| e.to_string())
    }

    async fn del(&self, key: &str) -> Result<u32, String> {
        let mut conn = self.redis.conn();
        conn.del(key).await.map_err(|e| e.to_string())
    }
}

#[async_trait]
impl SessionStorage for MemorySessionStorage {
    async fn set_ex(&self, key: &str, value: &str, _ttl_secs: u64) -> Result<(), String> {
        self.values
            .lock()
            .map_err(|_| "memory session storage lock poisoned".to_string())?
            .insert(key.to_string(), value.to_string());
        Ok(())
    }

    async fn get(&self, key: &str) -> Result<Option<String>, String> {
        Ok(self
            .values
            .lock()
            .map_err(|_| "memory session storage lock poisoned".to_string())?
            .get(key)
            .cloned())
    }

    async fn expire(&self, key: &str, _ttl_secs: u64) -> Result<bool, String> {
        Ok(self
            .values
            .lock()
            .map_err(|_| "memory session storage lock poisoned".to_string())?
            .contains_key(key))
    }

    async fn del(&self, key: &str) -> Result<u32, String> {
        Ok(self
            .values
            .lock()
            .map_err(|_| "memory session storage lock poisoned".to_string())?
            .remove(key)
            .map(|_| 1)
            .unwrap_or(0))
    }
}

pub struct SessionManager {
    storage: Arc<dyn SessionStorage>,
    ttl: Duration,
    /// Header names whose values are included in the client fingerprint.
    fingerprint_headers: Vec<String>,
    /// UUID that identifies this worker instance.
    worker_id: String,
}

impl SessionManager {
    /// Construct a new [`SessionManager`].
    ///
    /// * `redis` — pool used for all Redis operations.
    /// * `ttl_secs` — TTL applied to every session key.
    /// * `fingerprint_headers` — comma-separated list of header names whose
    ///   values contribute to the client fingerprint (e.g.
    ///   `"authorization,x-forwarded-for"`).
    pub fn new(redis: RedisPool, ttl_secs: u64, fingerprint_headers: &str) -> Self {
        Self::new_with_storage(
            Arc::new(RedisSessionStorage { redis }),
            ttl_secs,
            fingerprint_headers,
        )
    }

    #[doc(hidden)]
    pub fn new_ephemeral_for_tests(ttl_secs: u64, fingerprint_headers: &str) -> Self {
        Self::new_with_storage(
            Arc::new(MemorySessionStorage::default()),
            ttl_secs,
            fingerprint_headers,
        )
    }

    fn new_with_storage(
        storage: Arc<dyn SessionStorage>,
        ttl_secs: u64,
        fingerprint_headers: &str,
    ) -> Self {
        let headers = fingerprint_headers
            .split(',')
            .map(|h| h.trim().to_ascii_lowercase())
            .filter(|h| !h.is_empty())
            .collect();

        Self {
            storage,
            ttl: Duration::from_secs(ttl_secs),
            fingerprint_headers: headers,
            worker_id: Uuid::new_v4().to_string(),
        }
    }

    /// Compute a deterministic SHA-256 fingerprint from a set of HTTP headers.
    ///
    /// Only header names listed in `fingerprint_headers` are included.  Pairs
    /// are sorted by header name before hashing so that insertion order does
    /// not affect the result.
    pub fn compute_fingerprint(&self, headers: &HashMap<String, String>) -> String {
        fingerprint_from_headers(&self.fingerprint_headers, headers)
    }

    /// Create a new session in Redis.
    ///
    /// Returns the new session ID on success, or `None` if the Redis write
    /// fails.
    pub async fn create(&self, auth_context: &Value, fingerprint: &str) -> Option<String> {
        let session_id = Uuid::new_v4().to_string();
        let now_ms = now_ms();

        let record = SessionRecord {
            auth_context: auth_context.clone(),
            auth_fingerprint: fingerprint.to_owned(),
            worker_id: self.worker_id.clone(),
            created_at_ms: now_ms,
            last_active_at_ms: now_ms,
        };

        let json = match serde_json::to_string(&record) {
            Ok(j) => j,
            Err(e) => {
                warn!(error = %e, "session: failed to serialise SessionRecord");
                return None;
            }
        };

        let key = redis_key(&session_id);
        match self.storage.set_ex(&key, &json, self.ttl.as_secs()).await {
            Ok(()) => {
                debug!(session_id = %session_id, "session: created");
                Some(session_id)
            }
            Err(e) => {
                warn!(session_id = %session_id, error = %e, "session: Redis set_ex failed");
                None
            }
        }
    }

    /// Look up a session by ID.
    ///
    /// Returns `None` on a cache miss or if Redis is unavailable.
    pub async fn lookup(&self, session_id: &str) -> Option<SessionRecord> {
        let key = redis_key(session_id);
        match self.storage.get(&key).await {
            Ok(Some(json)) => match serde_json::from_str::<SessionRecord>(&json) {
                Ok(record) => {
                    debug!(session_id = %session_id, "session: found");
                    Some(record)
                }
                Err(e) => {
                    warn!(session_id = %session_id, error = %e, "session: JSON deserialise failed");
                    None
                }
            },
            Ok(None) => {
                debug!(session_id = %session_id, "session: not found");
                None
            }
            Err(e) => {
                warn!(session_id = %session_id, error = %e, "session: Redis get failed");
                None
            }
        }
    }

    /// Refresh the TTL of an existing session without modifying its contents.
    pub async fn extend(&self, session_id: &str) {
        let key = redis_key(session_id);
        match self.storage.expire(&key, self.ttl.as_secs()).await {
            Ok(true) => debug!(session_id = %session_id, "session: TTL extended"),
            Ok(false) => debug!(session_id = %session_id, "session: key not found during extend"),
            Err(e) => warn!(session_id = %session_id, error = %e, "session: expire failed"),
        }
    }

    /// Delete a session from Redis.
    pub async fn invalidate(&self, session_id: &str) {
        let key = redis_key(session_id);
        match self.storage.del(&key).await {
            Ok(_) => debug!(session_id = %session_id, "session: invalidated"),
            Err(e) => warn!(session_id = %session_id, error = %e, "session: del failed"),
        }
    }

    /// Return `true` if `fingerprint` matches the fingerprint stored in `session`.
    pub fn validate_fingerprint(&self, session: &SessionRecord, fingerprint: &str) -> bool {
        session.matches_fingerprint(fingerprint)
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Compute a SHA-256 fingerprint from a specific set of header names and a
/// map of header values.
///
/// This is a free function so that tests can exercise the hashing logic
/// without constructing a [`SessionManager`] (which requires a live Redis
/// connection).
fn fingerprint_from_headers(header_names: &[String], headers: &HashMap<String, String>) -> String {
    let mut pairs: Vec<String> = header_names
        .iter()
        .filter_map(|name| headers.get(name).map(|val| format!("{name}={val}")))
        .collect();
    pairs.sort();

    let mut hasher = Sha256::new();
    for pair in &pairs {
        hasher.update(pair.as_bytes());
        hasher.update(b"\n");
    }
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn redis_key(session_id: &str) -> String {
    format!("mcpgw:a2a:session:{session_id}")
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[derive(Default)]
    struct FakeSessionStorage {
        values: Mutex<HashMap<String, String>>,
        fail_set: Mutex<bool>,
        fail_get: Mutex<bool>,
        fail_expire: Mutex<bool>,
        fail_del: Mutex<bool>,
        expire_result: Mutex<bool>,
    }

    #[async_trait]
    impl SessionStorage for FakeSessionStorage {
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

        async fn get(&self, key: &str) -> Result<Option<String>, String> {
            if *self.fail_get.lock().unwrap() {
                return Err("get failed".to_string());
            }
            Ok(self.values.lock().unwrap().get(key).cloned())
        }

        async fn expire(&self, _key: &str, _ttl_secs: u64) -> Result<bool, String> {
            if *self.fail_expire.lock().unwrap() {
                return Err("expire failed".to_string());
            }
            Ok(*self.expire_result.lock().unwrap())
        }

        async fn del(&self, key: &str) -> Result<u32, String> {
            if *self.fail_del.lock().unwrap() {
                return Err("del failed".to_string());
            }
            Ok(self
                .values
                .lock()
                .unwrap()
                .remove(key)
                .map(|_| 1)
                .unwrap_or(0))
        }
    }

    fn fake_manager(storage: Arc<FakeSessionStorage>, fingerprint_headers: &str) -> SessionManager {
        SessionManager::new_with_storage(storage, 300, fingerprint_headers)
    }

    // -- SessionRecord serialization -----------------------------------------

    #[test]
    fn session_record_serialization_round_trip() {
        let record = SessionRecord {
            auth_context: serde_json::json!({"sub": "user@example.com", "roles": ["admin"]}),
            auth_fingerprint: "abc123".to_string(),
            worker_id: "worker-1".to_string(),
            created_at_ms: 1_700_000_000_000,
            last_active_at_ms: 1_700_000_001_000,
        };

        let json = serde_json::to_string(&record).expect("serialize");
        let decoded: SessionRecord = serde_json::from_str(&json).expect("deserialize");

        assert_eq!(decoded.auth_fingerprint, record.auth_fingerprint);
        assert_eq!(decoded.worker_id, record.worker_id);
        assert_eq!(decoded.created_at_ms, record.created_at_ms);
        assert_eq!(decoded.last_active_at_ms, record.last_active_at_ms);
        assert_eq!(decoded.auth_context, record.auth_context);
    }

    // -- compute_fingerprint -------------------------------------------------

    #[test]
    fn compute_fingerprint_deterministic() {
        // Use the module-level helper directly to avoid needing a live RedisPool.
        let header_names = vec!["authorization".to_string(), "x-forwarded-for".to_string()];
        let mut headers = HashMap::new();
        headers.insert("authorization".to_string(), "Bearer token123".to_string());
        headers.insert("x-forwarded-for".to_string(), "10.0.0.1".to_string());

        let fp1 = fingerprint_from_headers(&header_names, &headers);
        let fp2 = fingerprint_from_headers(&header_names, &headers);
        assert_eq!(fp1, fp2, "same headers must produce the same fingerprint");
    }

    #[test]
    fn compute_fingerprint_differs_for_different_values() {
        let header_names = vec!["authorization".to_string()];

        let mut headers_a = HashMap::new();
        headers_a.insert("authorization".to_string(), "Bearer tokenA".to_string());

        let mut headers_b = HashMap::new();
        headers_b.insert("authorization".to_string(), "Bearer tokenB".to_string());

        let fp_a = fingerprint_from_headers(&header_names, &headers_a);
        let fp_b = fingerprint_from_headers(&header_names, &headers_b);
        assert_ne!(
            fp_a, fp_b,
            "different auth values must produce different fingerprints"
        );
    }

    #[test]
    fn compute_fingerprint_ignores_unlisted_headers_and_order() {
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = fake_manager(storage, "x-forwarded-for,authorization");

        let mut headers_a = HashMap::new();
        headers_a.insert("authorization".to_string(), "Bearer token".to_string());
        headers_a.insert("x-forwarded-for".to_string(), "10.0.0.1".to_string());
        headers_a.insert("ignored".to_string(), "value-a".to_string());

        let mut headers_b = HashMap::new();
        headers_b.insert("x-forwarded-for".to_string(), "10.0.0.1".to_string());
        headers_b.insert("authorization".to_string(), "Bearer token".to_string());
        headers_b.insert("ignored".to_string(), "value-b".to_string());

        assert_eq!(
            manager.compute_fingerprint(&headers_a),
            manager.compute_fingerprint(&headers_b)
        );
    }

    #[tokio::test]
    async fn create_and_lookup_round_trip_uses_storage() {
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = fake_manager(Arc::clone(&storage), "authorization,cookie");
        let auth_context = serde_json::json!({"sub": "user@example.com"});

        let session_id = manager
            .create(&auth_context, "fingerprint-1")
            .await
            .expect("session should be created");

        let record = manager
            .lookup(&session_id)
            .await
            .expect("session should exist");
        assert_eq!(record.auth_context, auth_context);
        assert_eq!(record.auth_fingerprint, "fingerprint-1");
        assert!(!record.worker_id.is_empty());
        assert!(record.created_at_ms > 0);
        assert!(record.last_active_at_ms > 0);
    }

    #[tokio::test]
    async fn create_returns_none_when_storage_set_fails() {
        let storage = Arc::new(FakeSessionStorage::default());
        *storage.fail_set.lock().unwrap() = true;
        let manager = fake_manager(storage, "authorization");
        assert!(manager.create(&serde_json::json!({}), "fp").await.is_none());
    }

    #[tokio::test]
    async fn lookup_returns_none_for_miss_bad_json_and_storage_error() {
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = fake_manager(Arc::clone(&storage), "authorization");
        assert!(manager.lookup("missing").await.is_none());

        storage
            .values
            .lock()
            .unwrap()
            .insert(redis_key("broken"), "{not-json".to_string());
        assert!(manager.lookup("broken").await.is_none());

        *storage.fail_get.lock().unwrap() = true;
        assert!(manager.lookup("error").await.is_none());
    }

    #[tokio::test]
    async fn extend_and_invalidate_cover_success_false_and_error_paths() {
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = fake_manager(Arc::clone(&storage), "authorization");

        storage
            .values
            .lock()
            .unwrap()
            .insert(redis_key("session-1"), "value".to_string());

        *storage.expire_result.lock().unwrap() = true;
        manager.extend("session-1").await;

        *storage.expire_result.lock().unwrap() = false;
        manager.extend("session-1").await;

        *storage.fail_expire.lock().unwrap() = true;
        manager.extend("session-1").await;
        *storage.fail_expire.lock().unwrap() = false;

        manager.invalidate("session-1").await;
        assert!(
            !storage
                .values
                .lock()
                .unwrap()
                .contains_key(&redis_key("session-1"))
        );

        *storage.fail_del.lock().unwrap() = true;
        manager.invalidate("session-2").await;
    }

    // -- validate_fingerprint ------------------------------------------------

    #[test]
    fn fingerprint_validation_matches() {
        let record = SessionRecord {
            auth_context: serde_json::json!({}),
            auth_fingerprint: "deadbeef".to_string(),
            worker_id: "w".to_string(),
            created_at_ms: 0,
            last_active_at_ms: 0,
        };
        assert!(record.matches_fingerprint("deadbeef"));
    }

    #[test]
    fn fingerprint_validation_rejects_mismatch() {
        let record = SessionRecord {
            auth_context: serde_json::json!({}),
            auth_fingerprint: "deadbeef".to_string(),
            worker_id: "w".to_string(),
            created_at_ms: 0,
            last_active_at_ms: 0,
        };
        assert!(!record.matches_fingerprint("cafebabe"));
    }

    #[test]
    fn validate_fingerprint_delegates_to_record_match() {
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = fake_manager(storage, "authorization");
        let record = SessionRecord {
            auth_context: serde_json::json!({}),
            auth_fingerprint: "match-me".to_string(),
            worker_id: "worker".to_string(),
            created_at_ms: 0,
            last_active_at_ms: 0,
        };

        assert!(manager.validate_fingerprint(&record, "match-me"));
        assert!(!manager.validate_fingerprint(&record, "different"));
    }

    #[tokio::test]
    async fn concurrent_lookup_and_invalidate_leaves_storage_consistent() {
        // Simulate N concurrent invalidate+lookup pairs against the same
        // session_id.  The final state must be deterministic (session
        // absent) regardless of interleaving; no lookup may return a
        // partially-deleted row, and crucially: across all concurrent
        // tasks the lookup must observe either the full record or
        // ``None`` — never a record with a partially-cleared field.
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = Arc::new(fake_manager(Arc::clone(&storage), "authorization"));

        let sid = manager
            .create(&serde_json::json!({"sub": "u", "roles": ["admin"]}), "fp-1")
            .await
            .expect("create session");

        let mut handles = Vec::new();
        for _ in 0..32 {
            let mgr = Arc::clone(&manager);
            let sid_clone = sid.clone();
            handles.push(tokio::spawn(async move {
                // Yield once before AND once between operations to widen
                // the interleaving window — without yield_now, individual
                // tasks tend to run their two ops back-to-back under the
                // current-thread runtime, masking races.
                tokio::task::yield_now().await;
                let observed = mgr.lookup(&sid_clone).await;
                tokio::task::yield_now().await;
                mgr.invalidate(&sid_clone).await;
                observed
            }));
        }

        // Collect every observation; assert the invariant: each is either
        // the full record (with both fields intact) or absent.  A
        // partial/torn read would fail the integrity check.
        for h in handles {
            let observed = h.await.expect("task join");
            if let Some(record) = observed {
                assert_eq!(
                    record.auth_context,
                    serde_json::json!({"sub": "u", "roles": ["admin"]}),
                    "lookup returned partial/torn record under concurrent invalidate"
                );
                assert_eq!(record.auth_fingerprint, "fp-1");
            }
        }

        assert!(
            manager.lookup(&sid).await.is_none(),
            "session must be absent after concurrent invalidations"
        );
    }

    #[tokio::test]
    async fn concurrent_create_produces_distinct_session_ids() {
        // Two concurrent create() calls must produce distinct session IDs
        // — a shared counter or non-UUID scheme would break here.
        let storage = Arc::new(FakeSessionStorage::default());
        let manager = Arc::new(fake_manager(Arc::clone(&storage), "authorization"));

        let mut handles = Vec::new();
        for i in 0..16 {
            let mgr = Arc::clone(&manager);
            handles.push(tokio::spawn(async move {
                mgr.create(&serde_json::json!({"sub": format!("u{i}")}), "fp")
                    .await
            }));
        }
        let mut ids: Vec<String> = Vec::new();
        for h in handles {
            if let Some(sid) = h.await.expect("task join") {
                ids.push(sid);
            }
        }
        let unique: std::collections::HashSet<&String> = ids.iter().collect();
        assert_eq!(unique.len(), ids.len(), "session IDs must be unique");
    }
}
