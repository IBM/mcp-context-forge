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
use async_trait::async_trait;
use redis::AsyncCommands;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
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
#[async_trait]
trait EventStoreStorage: Send + Sync {
    #[allow(clippy::too_many_arguments)]
    async fn store_event(
        &self,
        meta_key: &str,
        events_key: &str,
        messages_key: &str,
        event_id: &str,
        payload_json: &str,
        ttl_secs: u64,
        max_events: usize,
    ) -> Result<i64, String>;
    async fn replay_entries(
        &self,
        events_key: &str,
        after_sequence: i64,
    ) -> Result<Vec<(String, f64)>, String>;
    async fn payloads(
        &self,
        messages_key: &str,
        event_ids: &[String],
    ) -> Result<Vec<Option<String>>, String>;
    async fn hget(&self, key: &str, field: &str) -> Result<Option<String>, String>;
    async fn hset(&self, key: &str, field: &str, value: &str) -> Result<(), String>;
}

struct RedisEventStoreStorage {
    redis: RedisPool,
}

#[async_trait]
impl EventStoreStorage for RedisEventStoreStorage {
    #[allow(clippy::too_many_arguments)]
    async fn store_event(
        &self,
        meta_key: &str,
        events_key: &str,
        messages_key: &str,
        event_id: &str,
        payload_json: &str,
        ttl_secs: u64,
        max_events: usize,
    ) -> Result<i64, String> {
        redis::cmd("EVAL")
            .arg(STORE_EVENT_LUA)
            .arg(3_u8)
            .arg(meta_key)
            .arg(events_key)
            .arg(messages_key)
            .arg(event_id)
            .arg(payload_json)
            .arg(ttl_secs)
            .arg(max_events)
            .query_async(&mut self.redis.conn())
            .await
            .map_err(|e| e.to_string())
    }

    async fn replay_entries(
        &self,
        events_key: &str,
        after_sequence: i64,
    ) -> Result<Vec<(String, f64)>, String> {
        self.redis
            .conn()
            .zrangebyscore_withscores(events_key, after_sequence + 1, "+inf")
            .await
            .map_err(|e| e.to_string())
    }

    async fn payloads(
        &self,
        messages_key: &str,
        event_ids: &[String],
    ) -> Result<Vec<Option<String>>, String> {
        redis::cmd("HMGET")
            .arg(messages_key)
            .arg(event_ids)
            .query_async(&mut self.redis.conn())
            .await
            .map_err(|e| e.to_string())
    }

    async fn hget(&self, key: &str, field: &str) -> Result<Option<String>, String> {
        self.redis
            .conn()
            .hget(key, field)
            .await
            .map_err(|e| e.to_string())
    }

    async fn hset(&self, key: &str, field: &str, value: &str) -> Result<(), String> {
        self.redis
            .conn()
            .hset(key, field, value)
            .await
            .map_err(|e| e.to_string())
    }
}

pub struct EventStore {
    storage: Arc<dyn EventStoreStorage>,
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
        Self::new_with_storage(
            Arc::new(RedisEventStoreStorage { redis }),
            max_events,
            ttl_secs,
            flush_tx,
        )
    }

    fn new_with_storage(
        storage: Arc<dyn EventStoreStorage>,
        max_events: usize,
        ttl_secs: u64,
        flush_tx: mpsc::Sender<FlushEntry>,
    ) -> Self {
        Self {
            storage,
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

        let sequence: i64 = match self
            .storage
            .store_event(
                &meta_key,
                &events_key,
                &messages_key,
                &event_id,
                &payload_json,
                self.ttl_secs,
                self.max_events,
            )
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
        let entries: Vec<(String, f64)> = match self
            .storage
            .replay_entries(&events_key, after_sequence)
            .await
        {
            Ok(e) => e,
            Err(e) => {
                warn!(task_id, "failed to replay events from Redis: {e}");
                return vec![];
            }
        };

        if entries.is_empty() {
            return vec![];
        }

        let event_ids: Vec<String> = entries
            .iter()
            .map(|(event_id, _)| event_id.clone())
            .collect();
        let payloads: Vec<Option<String>> =
            match self.storage.payloads(&messages_key, &event_ids).await {
                Ok(payloads) => payloads,
                Err(e) => {
                    warn!(task_id, "failed to fetch replay payloads from Redis: {e}");
                    return vec![];
                }
            };

        let mut result = Vec::with_capacity(entries.len());
        for ((event_id, score), payload) in entries.into_iter().zip(payloads) {
            result.push(StoredEvent {
                event_id,
                sequence: score as i64,
                // Event type is not stored separately in the Redis ring buffer;
                // callers should resolve the type from the payload if needed.
                event_type: "unknown".to_string(),
                payload: payload.unwrap_or_default(),
            });
        }
        result
    }

    /// Return `true` if the stream is still active (agent has not finished).
    pub async fn is_stream_active(&self, task_id: &str) -> bool {
        let meta_key = format!("{KEY_PREFIX}:{task_id}:meta");
        let active: Option<String> = self
            .storage
            .hget(&meta_key, "stream_active")
            .await
            .unwrap_or(None);
        active.as_deref() == Some("1")
    }

    /// Mark the stream as complete (agent has finished sending events).
    pub async fn mark_stream_complete(&self, task_id: &str) {
        let meta_key = format!("{KEY_PREFIX}:{task_id}:meta");
        let _ = self.storage.hset(&meta_key, "stream_active", "0").await;
    }

    #[doc(hidden)]
    pub fn seeded_for_test(events: Vec<StoredEvent>, stream_active: bool) -> Self {
        #[derive(Clone)]
        struct SeededEventStoreStorage {
            events: Arc<Vec<StoredEvent>>,
            active: bool,
        }

        #[async_trait]
        impl EventStoreStorage for SeededEventStoreStorage {
            async fn store_event(
                &self,
                _meta_key: &str,
                _events_key: &str,
                _messages_key: &str,
                _event_id: &str,
                _payload_json: &str,
                _ttl_secs: u64,
                _max_events: usize,
            ) -> Result<i64, String> {
                Err("store not supported in seeded test store".to_string())
            }

            async fn replay_entries(
                &self,
                _events_key: &str,
                after_sequence: i64,
            ) -> Result<Vec<(String, f64)>, String> {
                Ok(self
                    .events
                    .iter()
                    .filter(|event| event.sequence > after_sequence)
                    .map(|event| (event.event_id.clone(), event.sequence as f64))
                    .collect())
            }

            async fn payloads(
                &self,
                _messages_key: &str,
                event_ids: &[String],
            ) -> Result<Vec<Option<String>>, String> {
                Ok(event_ids
                    .iter()
                    .map(|event_id| {
                        self.events
                            .iter()
                            .find(|event| &event.event_id == event_id)
                            .map(|event| event.payload.clone())
                    })
                    .collect())
            }

            async fn hget(&self, _key: &str, _field: &str) -> Result<Option<String>, String> {
                Ok(Some(if self.active { "1" } else { "0" }.to_string()))
            }

            async fn hset(&self, _key: &str, _field: &str, _value: &str) -> Result<(), String> {
                Ok(())
            }
        }

        let (flush_tx, _flush_rx) = mpsc::channel(1);
        Self::new_with_storage(
            Arc::new(SeededEventStoreStorage {
                events: Arc::new(events),
                active: stream_active,
            }),
            256,
            60,
            flush_tx,
        )
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
    auth_secret: &str, // pragma: allowlist secret
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
    use std::collections::HashMap;
    use std::sync::Mutex;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[derive(Default)]
    struct FakeEventStoreStorage {
        next_sequence: Mutex<i64>,
        entries: Mutex<Vec<(String, i64)>>,
        payloads: Mutex<HashMap<String, String>>,
        stream_active: Mutex<Option<String>>,
        fail_store: Mutex<bool>,
        fail_replay: Mutex<bool>,
        fail_payloads: Mutex<bool>,
        fail_hget: Mutex<bool>,
        fail_hset: Mutex<bool>,
    }

    #[async_trait]
    impl EventStoreStorage for FakeEventStoreStorage {
        async fn store_event(
            &self,
            _meta_key: &str,
            _events_key: &str,
            _messages_key: &str,
            event_id: &str,
            payload_json: &str,
            _ttl_secs: u64,
            max_events: usize,
        ) -> Result<i64, String> {
            if *self.fail_store.lock().unwrap() {
                return Err("store failed".to_string());
            }
            let mut next_sequence = self.next_sequence.lock().unwrap();
            *next_sequence += 1;
            let sequence = *next_sequence;

            let mut entries = self.entries.lock().unwrap();
            entries.push((event_id.to_string(), sequence));
            if entries.len() > max_events {
                let excess = entries.len() - max_events;
                let removed: Vec<String> = entries
                    .drain(0..excess)
                    .map(|(event_id, _)| event_id)
                    .collect();
                let mut payloads = self.payloads.lock().unwrap();
                for event_id in removed {
                    payloads.remove(&event_id);
                }
            }

            self.payloads
                .lock()
                .unwrap()
                .insert(event_id.to_string(), payload_json.to_string());
            *self.stream_active.lock().unwrap() = Some("1".to_string());
            Ok(sequence)
        }

        async fn replay_entries(
            &self,
            _events_key: &str,
            after_sequence: i64,
        ) -> Result<Vec<(String, f64)>, String> {
            if *self.fail_replay.lock().unwrap() {
                return Err("replay failed".to_string());
            }
            Ok(self
                .entries
                .lock()
                .unwrap()
                .iter()
                .filter(|(_, sequence)| *sequence > after_sequence)
                .map(|(event_id, sequence)| (event_id.clone(), *sequence as f64))
                .collect())
        }

        async fn payloads(
            &self,
            _messages_key: &str,
            event_ids: &[String],
        ) -> Result<Vec<Option<String>>, String> {
            if *self.fail_payloads.lock().unwrap() {
                return Err("payload lookup failed".to_string());
            }
            let payloads = self.payloads.lock().unwrap();
            Ok(event_ids
                .iter()
                .map(|event_id| payloads.get(event_id).cloned())
                .collect())
        }

        async fn hget(&self, _key: &str, _field: &str) -> Result<Option<String>, String> {
            if *self.fail_hget.lock().unwrap() {
                return Err("hget failed".to_string());
            }
            Ok(self.stream_active.lock().unwrap().clone())
        }

        async fn hset(&self, _key: &str, _field: &str, value: &str) -> Result<(), String> {
            if *self.fail_hset.lock().unwrap() {
                return Err("hset failed".to_string());
            }
            *self.stream_active.lock().unwrap() = Some(value.to_string());
            Ok(())
        }
    }

    #[test]
    #[allow(clippy::const_is_empty)]
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

    #[tokio::test]
    async fn flush_batch_posts_events_and_clears_buffer() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/events/flush"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&mock_server)
            .await;

        let client = Client::new();
        let mut buffer = vec![FlushEntry {
            task_id: "task-1".to_string(),
            event_id: "evt-1".to_string(),
            sequence: 1,
            event_type: "status".to_string(),
            payload: serde_json::json!({"status": "working"}),
        }];

        flush_batch(&client, &mock_server.uri(), "secret", &mut buffer).await;

        assert!(buffer.is_empty(), "flush should drain the buffered entries");
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn flush_batch_handles_non_success_and_network_error() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/events/flush"))
            .respond_with(ResponseTemplate::new(500))
            .expect(1)
            .mount(&mock_server)
            .await;

        let client = Client::new();
        let mut buffer = vec![FlushEntry {
            task_id: "task-2".to_string(),
            event_id: "evt-2".to_string(),
            sequence: 2,
            event_type: "status".to_string(),
            payload: serde_json::json!({"status": "failed"}),
        }];
        flush_batch(&client, &mock_server.uri(), "secret", &mut buffer).await;
        assert!(buffer.is_empty());

        let mut network_error_buffer = vec![FlushEntry {
            task_id: "task-3".to_string(),
            event_id: "evt-3".to_string(),
            sequence: 3,
            event_type: "status".to_string(),
            payload: serde_json::json!({"status": "errored"}),
        }];
        flush_batch(
            &client,
            "http://127.0.0.1:1",
            "secret",
            &mut network_error_buffer,
        )
        .await;
        assert!(network_error_buffer.is_empty());
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn spawn_flush_task_flushes_on_receiver_close() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/events/flush"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&mock_server)
            .await;

        let (tx, rx) = mpsc::channel(4);
        let handle = spawn_flush_task(
            rx,
            Client::new(),
            mock_server.uri(),
            "secret".to_string(),
            Duration::from_secs(60),
            10,
        );

        tx.send(FlushEntry {
            task_id: "task-4".to_string(),
            event_id: "evt-4".to_string(),
            sequence: 4,
            event_type: "status".to_string(),
            payload: serde_json::json!({"status": "done"}),
        })
        .await
        .unwrap();
        drop(tx);

        handle.await.unwrap();
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn spawn_flush_task_flushes_when_batch_size_is_reached() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/events/flush"))
            .respond_with(ResponseTemplate::new(204))
            .expect(1)
            .mount(&mock_server)
            .await;

        let (tx, rx) = mpsc::channel(4);
        let handle = spawn_flush_task(
            rx,
            Client::new(),
            mock_server.uri(),
            "secret".to_string(),
            Duration::from_secs(60),
            1,
        );

        tx.send(FlushEntry {
            task_id: "task-5".to_string(),
            event_id: "evt-5".to_string(),
            sequence: 5,
            event_type: "status".to_string(),
            payload: serde_json::json!({"status": "done"}),
        })
        .await
        .unwrap();
        drop(tx);

        handle.await.unwrap();
        mock_server.verify().await;
    }

    #[tokio::test]
    async fn store_event_and_replay_after_use_storage_and_trim_ring_buffer() {
        let storage = Arc::new(FakeEventStoreStorage::default());
        let (flush_tx, mut flush_rx) = mpsc::channel(1);
        let store = EventStore::new_with_storage(storage, 2, 60, flush_tx);

        let (_, seq1) = store
            .store_event("task-1", "status", &serde_json::json!({"n": 1}))
            .await
            .expect("first event");
        let (_, seq2) = store
            .store_event("task-1", "status", &serde_json::json!({"n": 2}))
            .await
            .expect("second event");
        let (_, seq3) = store
            .store_event("task-1", "status", &serde_json::json!({"n": 3}))
            .await
            .expect("third event");

        assert_eq!(seq1, 1);
        assert_eq!(seq2, 2);
        assert_eq!(seq3, 3);

        let flushed = flush_rx.recv().await.expect("flush entry should exist");
        assert_eq!(flushed.task_id, "task-1");

        let replayed = store.replay_after("task-1", 0).await;
        assert_eq!(
            replayed.len(),
            2,
            "ring buffer should retain only max_events"
        );
        assert_eq!(replayed[0].sequence, 2);
        assert_eq!(replayed[1].sequence, 3);
        assert_eq!(replayed[0].event_type, "unknown");
    }

    #[tokio::test]
    async fn event_store_handles_storage_failures_and_stream_state() {
        let storage = Arc::new(FakeEventStoreStorage::default());
        let (flush_tx, _flush_rx) = mpsc::channel(1);
        let store = EventStore::new_with_storage(
            storage.clone() as Arc<dyn EventStoreStorage>,
            10,
            60,
            flush_tx,
        );

        *storage.fail_store.lock().unwrap() = true;
        assert!(
            store
                .store_event("task-2", "status", &serde_json::json!({"n": 1}))
                .await
                .is_none()
        );
        *storage.fail_store.lock().unwrap() = false;

        *storage.fail_replay.lock().unwrap() = true;
        assert!(store.replay_after("task-2", 0).await.is_empty());
        *storage.fail_replay.lock().unwrap() = false;

        *storage.fail_payloads.lock().unwrap() = true;
        assert!(store.replay_after("task-2", 0).await.is_empty());
        *storage.fail_payloads.lock().unwrap() = false;

        *storage.stream_active.lock().unwrap() = Some("1".to_string());
        assert!(store.is_stream_active("task-2").await);
        *storage.stream_active.lock().unwrap() = Some("0".to_string());
        assert!(!store.is_stream_active("task-2").await);

        *storage.fail_hget.lock().unwrap() = true;
        assert!(!store.is_stream_active("task-2").await);
        *storage.fail_hget.lock().unwrap() = false;

        store.mark_stream_complete("task-2").await;
        assert_eq!(storage.stream_active.lock().unwrap().as_deref(), Some("0"));

        *storage.fail_hset.lock().unwrap() = true;
        store.mark_stream_complete("task-2").await;
    }
}
