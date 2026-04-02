// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Redis-backed session management for A2A authenticated streams.
//!
//! A [`SessionRecord`] binds an authenticated identity to a fingerprint of
//! the client's auth headers.  [`SessionManager`] stores session records in
//! Redis under the key `mcpgw:a2a:session:{session_id}` with a configurable
//! TTL that can be refreshed on activity.

use crate::cache::RedisPool;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
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
pub struct SessionManager {
    redis: RedisPool,
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
        let headers = fingerprint_headers
            .split(',')
            .map(|h| h.trim().to_ascii_lowercase())
            .filter(|h| !h.is_empty())
            .collect();

        Self {
            redis,
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
        let mut conn = self.redis.conn();
        let result: Result<(), _> = conn.set_ex(&key, &json, self.ttl.as_secs()).await;
        match result {
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
        let mut conn = self.redis.conn();
        let result: Result<Option<String>, _> = conn.get(&key).await;
        match result {
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
        let mut conn = self.redis.conn();
        let result: Result<bool, _> = conn.expire(&key, self.ttl.as_secs() as i64).await;
        match result {
            Ok(true) => debug!(session_id = %session_id, "session: TTL extended"),
            Ok(false) => debug!(session_id = %session_id, "session: key not found during extend"),
            Err(e) => warn!(session_id = %session_id, error = %e, "session: expire failed"),
        }
    }

    /// Delete a session from Redis.
    pub async fn invalidate(&self, session_id: &str) {
        let key = redis_key(session_id);
        let mut conn = self.redis.conn();
        let result: Result<u32, _> = conn.del(&key).await;
        match result {
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
    format!("{:x}", hasher.finalize())
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
}
