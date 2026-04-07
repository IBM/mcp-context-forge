// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Redis ring-buffer event store for SSE streaming events.
//!
//! [`EventStore`] stores task events in three Redis keys per task:
//!
//! - `mcpgw:a2a:events:{task_id}:meta`     — HSET with `next_seq` and `stream_active`
//! - `mcpgw:a2a:events:{task_id}:events`   — ZSET mapping event_id → sequence score
//! - `mcpgw:a2a:events:{task_id}:messages` — HSET mapping event_id → payload JSON
//!
//! A Lua script performs all three writes atomically and enforces a ring-buffer
//! size limit (`max_events`).  A background flush task drains a channel of
//! [`FlushEntry`] items and batches them to the Python gateway for durable PG
//! persistence.

use crate::cache::RedisPool;
use crate::trust;
use redis::AsyncCommands;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use tokio::sync::mpsc;
use tracing::{debug, warn};
use uuid::Uuid;

const KEY_PREFIX: &str = "mcpgw:a2a:events";

// ---------------------------------------------------------------------------
// Lua script — atomic ring-buffer store
// ---------------------------------------------------------------------------

const STORE_EVENT_LUA: &str = r#"
local meta_key = KEYS[1]
local events_key = KEYS[2]
local messages_key = KEYS[3]
local event_id = ARGV[1]
local payload = ARGV[2]
local ttl = tonumber(ARGV[3])
local max_events = tonumber(ARGV[4])

local seq = redis.call('HINCRBY', meta_key, 'next_seq', 1)
redis.call('HSET', meta_key, 'stream_active', '1')
redis.call('ZADD', events_key, seq, event_id)
redis.call('HSET', messages_key, event_id, payload)

local count = redis.call('ZCARD', events_key)
if count > max_events then
    local excess = count - max_events
    local old_ids = redis.call('ZRANGE', events_key, 0, excess - 1)
    redis.call('ZREMRANGEBYRANK', events_key, 0, excess - 1)
    for _, old_id in ipairs(old_ids) do
        redis.call('HDEL', messages_key, old_id)
    end
end

redis.call('EXPIRE', meta_key, ttl)
redis.call('EXPIRE', events_key, ttl)
redis.call('EXPIRE', messages_key, ttl)

return seq
"#;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// A single event queued for durable PG persistence.
pub struct FlushEntry {
    pub task_id: String,
    pub event_id: String,
    pub sequence: i64,
    pub event_type: String,
    pub payload: Value,
}

/// An event retrieved from the Redis ring buffer during replay.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredEvent {
    pub event_id: String,
    pub sequence: i64,
    pub event_type: String,
    pub payload: String,
}

// ---------------------------------------------------------------------------
// EventStore
// ---------------------------------------------------------------------------

/// Redis-backed ring-buffer store for SSE streaming events.
pub struct EventStore {
    redis: RedisPool,
    max_events: usize,
    ttl_secs: u64,
    flush_tx: mpsc::Sender<FlushEntry>,
}

impl EventStore {
    /// Create a new [`EventStore`].
    ///
    /// * `redis`      — shared Redis connection pool.
    /// * `max_events` — maximum events retained per task (ring-buffer size).
    /// * `ttl_secs`   — Redis key TTL in seconds (applied after every write).
    /// * `flush_tx`   — sender half of the channel consumed by [`spawn_flush_task`].
    pub fn new(
        redis: RedisPool,
        max_events: usize,
        ttl_secs: u64,
        flush_tx: mpsc::Sender<FlushEntry>,
    ) -> Self {
        Self {
            redis,
            max_events,
            ttl_secs,
            flush_tx,
        }
    }

    /// Store an event in the Redis ring buffer and enqueue it for PG flush.
    ///
    /// Returns `Some((event_id, sequence))` on success or `None` if the Redis
    /// write failed.
    pub async fn store_event(
        &self,
        task_id: &str,
        event_type: &str,
        payload: &Value,
    ) -> Option<(String, i64)> {
        let event_id = Uuid::new_v4().to_string();
        let payload_json = serde_json::to_string(payload).unwrap_or_default();

        let meta_key = format!("{KEY_PREFIX}:{task_id}:meta");
        let events_key = format!("{KEY_PREFIX}:{task_id}:events");
        let messages_key = format!("{KEY_PREFIX}:{task_id}:messages");

        let sequence: i64 = match redis::cmd("EVAL")
            .arg(STORE_EVENT_LUA)
            .arg(3_u8) // number of keys
            .arg(&meta_key)
            .arg(&events_key)
            .arg(&messages_key)
            .arg(&event_id)
            .arg(&payload_json)
            .arg(self.ttl_secs)
            .arg(self.max_events)
            .query_async(&mut self.redis.conn())
            .await
        {
            Ok(seq) => seq,
            Err(e) => {
                warn!(task_id, "failed to store event in Redis: {e}");
                return None;
            }
        };

        // Send to flush channel (best-effort; drop on full channel).
        let _ = self.flush_tx.try_send(FlushEntry {
            task_id: task_id.to_owned(),
            event_id: event_id.clone(),
            sequence,
            event_type: event_type.to_owned(),
            payload: payload.clone(),
        });

        Some((event_id, sequence))
    }

    /// Replay events from Redis with a sequence number strictly greater than
    /// `after_sequence`.
    pub async fn replay_after(&self, task_id: &str, after_sequence: i64) -> Vec<StoredEvent> {
        let events_key = format!("{KEY_PREFIX}:{task_id}:events");
        let messages_key = format!("{KEY_PREFIX}:{task_id}:messages");

        // Scores are integer sequences; range is exclusive lower bound.
        let min_score = after_sequence + 1;
        let entries: Vec<(String, f64)> = match self
            .redis
            .conn()
            .zrangebyscore_withscores(&events_key, min_score, "+inf")
            .await
        {
            Ok(e) => e,
            Err(e) => {
                warn!(task_id, "failed to replay events from Redis: {e}");
                return vec![];
            }
        };

        let mut result = Vec::with_capacity(entries.len());
        for (event_id, score) in entries {
            let payload: String = self
                .redis
                .conn()
                .hget(&messages_key, &event_id)
                .await
                .unwrap_or_default();
            result.push(StoredEvent {
                event_id,
                sequence: score as i64,
                // Event type is not stored separately in the Redis ring buffer;
                // callers should resolve the type from the payload if needed.
                event_type: "unknown".to_string(),
                payload,
            });
        }
        result
    }

    /// Return `true` if the stream is still active (agent has not finished).
    pub async fn is_stream_active(&self, task_id: &str) -> bool {
        let meta_key = format!("{KEY_PREFIX}:{task_id}:meta");
        let active: Option<String> = self
            .redis
            .conn()
            .hget(&meta_key, "stream_active")
            .await
            .unwrap_or(None);
        active.as_deref() == Some("1")
    }

    /// Mark the stream as complete (agent has finished sending events).
    pub async fn mark_stream_complete(&self, task_id: &str) {
        let meta_key = format!("{KEY_PREFIX}:{task_id}:meta");
        let _: Result<(), _> = self
            .redis
            .conn()
            .hset(&meta_key, "stream_active", "0")
            .await;
    }
}

// ---------------------------------------------------------------------------
// Flush background task
// ---------------------------------------------------------------------------

/// Spawn a background Tokio task that drains [`FlushEntry`] items from `rx`
/// and POSTs them in batches to the Python gateway for durable PG persistence.
///
/// * `interval`   — how often to flush a partial batch even if `batch_size` is
///   not yet reached.
/// * `batch_size` — flush immediately when this many entries are buffered.
pub fn spawn_flush_task(
    mut rx: mpsc::Receiver<FlushEntry>,
    client: Client,
    backend_base_url: String,
    auth_secret: String,
    interval: Duration,
    batch_size: usize,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut buffer: Vec<FlushEntry> = Vec::with_capacity(batch_size);
        let mut flush_interval = tokio::time::interval(interval);
        flush_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                entry = rx.recv() => {
                    match entry {
                        Some(e) => {
                            buffer.push(e);
                            if buffer.len() >= batch_size {
                                flush_batch(&client, &backend_base_url, &auth_secret, &mut buffer).await;
                            }
                        }
                        None => {
                            // Channel closed — flush remaining entries and exit.
                            if !buffer.is_empty() {
                                flush_batch(&client, &backend_base_url, &auth_secret, &mut buffer).await;
                            }
                            break;
                        }
                    }
                }
                _ = flush_interval.tick() => {
                    if !buffer.is_empty() {
                        flush_batch(&client, &backend_base_url, &auth_secret, &mut buffer).await;
                    }
                }
            }
        }
    })
}

async fn flush_batch(
    client: &Client,
    backend_base_url: &str,
    auth_secret: &str,  // pragma: allowlist secret
    buffer: &mut Vec<FlushEntry>,
) {
    let url = format!(
        "{}/_internal/a2a/events/flush",
        backend_base_url.trim_end_matches('/')
    );
    let headers = trust::build_trust_headers(auth_secret);
    let events: Vec<_> = buffer
        .drain(..)
        .map(|e| {
            serde_json::json!({
                "task_id": e.task_id,
                "event_id": e.event_id,
                "sequence": e.sequence,
                "event_type": e.event_type,
                "payload": e.payload,
            })
        })
        .collect();

    let count = events.len();
    match client
        .post(&url)
        .headers(trust::reqwest_headers(&headers))
        .json(&serde_json::json!({"events": events}))
        .send()
        .await
    {
        Ok(resp) if resp.status().is_success() => {
            debug!(count, "flushed events to PG");
        }
        Ok(resp) => {
            warn!(status = resp.status().as_u16(), "event flush failed");
        }
        Err(e) => {
            warn!("event flush request failed: {e}");
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn store_event_lua_script_is_valid_string() {
        assert!(!STORE_EVENT_LUA.is_empty());
        // Sanity-check key Lua constructs are present.
        assert!(STORE_EVENT_LUA.contains("HINCRBY"));
        assert!(STORE_EVENT_LUA.contains("ZADD"));
        assert!(STORE_EVENT_LUA.contains("EXPIRE"));
    }

    #[test]
    fn flush_entry_fields() {
        let payload = serde_json::json!({"status": "working"});
        let entry = FlushEntry {
            task_id: "task-abc".to_string(),
            event_id: "ev-001".to_string(),
            sequence: 7,
            event_type: "status_update".to_string(),
            payload: payload.clone(),
        };
        assert_eq!(entry.task_id, "task-abc");
        assert_eq!(entry.event_id, "ev-001");
        assert_eq!(entry.sequence, 7);
        assert_eq!(entry.event_type, "status_update");
        assert_eq!(entry.payload, payload);
    }

    #[test]
    fn stored_event_serialization() {
        let event = StoredEvent {
            event_id: "ev-123".to_string(),
            sequence: 42,
            event_type: "artifact_update".to_string(),
            payload: r#"{"artifact":"data"}"#.to_string(),
        };
        let json = serde_json::to_string(&event).expect("serialize");
        let decoded: StoredEvent = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(decoded.event_id, event.event_id);
        assert_eq!(decoded.sequence, event.sequence);
        assert_eq!(decoded.event_type, event.event_type);
        assert_eq!(decoded.payload, event.payload);
    }
}
