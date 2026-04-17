// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Bounded-concurrency job queue with request coalescing.
//!
//! A dedicated OS thread runs its own single-threaded Tokio runtime.  The
//! main Axum server submits jobs via a channel; the worker thread executes
//! them with bounded concurrency via a semaphore.  Within each batch,
//! requests sharing the same `request_id` are deduplicated — one HTTP call,
//! result cloned to all callers.

use crate::circuit::CircuitBreaker;
use crate::config::RuntimeConfig;
use crate::http::ResolvedRequest;
use crate::invoke::{self, InvokeContext, InvokeResult};
use crate::metrics::MetricsCollector;
use reqwest::Client;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};
use tokio::sync::{Semaphore, mpsc, oneshot};
use tokio::task::JoinSet;
use tracing::{debug, error, info, warn};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// Result for a single request within a job.
#[derive(Debug, Clone)]
pub struct JobResult {
    /// Positional index within the original request batch.
    pub id: usize,
    /// The invoke result (shared via `Arc` for coalesced requests).
    pub result: Arc<Result<InvokeResult, String>>,
    /// Wall-clock duration of the invocation.
    pub duration: Duration,
    /// Agent name echoed back for correlation.
    pub agent_name: Option<String>,
}

/// Errors returned by queue operations.
#[derive(Debug, thiserror::Error)]
pub enum QueueError {
    #[error("queue is full")]
    Full,
    #[error("queue not initialized")]
    NotInitialized,
    #[error("queue is shutting down")]
    Shutdown,
}

/// Shared state passed to the worker thread.
pub struct WorkerState {
    pub client: Client,
    pub config: Arc<RuntimeConfig>,
    pub circuit: Arc<CircuitBreaker>,
    pub metrics: Arc<MetricsCollector>,
}

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

/// A batch of requests plus a channel to return results.
struct Job {
    requests: Vec<ResolvedRequest>,
    timeout: Duration,
    result_tx: oneshot::Sender<Vec<JobResult>>,
}

/// Messages sent from the main Axum server to the worker thread.
enum QueueMessage {
    Job(Job),
    Shutdown {
        drain_timeout: Duration,
        ack: oneshot::Sender<()>,
    },
}

/// Abstraction over the queue sender.
#[derive(Debug)]
enum QueueSender {
    Bounded(mpsc::Sender<QueueMessage>),
}

impl QueueSender {
    /// Non-blocking send.  Returns [`QueueError::Full`] when the queue is at
    /// capacity, or [`QueueError::Shutdown`] when the receiver has been dropped.
    fn try_send(&self, msg: QueueMessage) -> Result<(), QueueError> {
        match self {
            QueueSender::Bounded(tx) => tx.try_send(msg).map_err(|e| match e {
                mpsc::error::TrySendError::Full(_) => QueueError::Full,
                mpsc::error::TrySendError::Closed(_) => QueueError::Shutdown,
            }),
        }
    }
}

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

static SENDER: OnceLock<QueueSender> = OnceLock::new();
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);

/// Maximum number of requests that may be coalesced into a single batch.
const MAX_COALESCED_REQUESTS: usize = 128;

// ---------------------------------------------------------------------------
// Coalescing
// ---------------------------------------------------------------------------

/// Drain the receiver non-blockingly, collecting consecutive `Job` messages.
///
/// Jobs with matching `timeout` and a combined request count under
/// [`MAX_COALESCED_REQUESTS`] are considered part of the same logical batch
/// (coalesced at the request-ID level during execution).  Jobs that exceed
/// the limit or have a different timeout are still returned — the caller
/// processes them all.
///
/// Any non-`Job` messages (i.e., `Shutdown`) are returned separately so the
/// caller can handle them after processing the jobs.
fn coalesce_jobs(
    first: Job,
    receiver: &mut mpsc::Receiver<QueueMessage>,
) -> (Vec<Job>, Vec<QueueMessage>) {
    let mut jobs = vec![first];
    let mut non_job_messages: Vec<QueueMessage> = Vec::new();
    let mut total_requests: usize = jobs[0].requests.len();

    loop {
        // Stop coalescing once we have enough requests.
        if total_requests >= MAX_COALESCED_REQUESTS {
            break;
        }

        match receiver.try_recv() {
            Ok(QueueMessage::Job(job)) => {
                total_requests += job.requests.len();
                jobs.push(job);
            }
            Ok(other @ QueueMessage::Shutdown { .. }) => {
                non_job_messages.push(other);
                break;
            }
            Err(_) => break,
        }
    }

    (jobs, non_job_messages)
}

// ---------------------------------------------------------------------------
// Worker loop
// ---------------------------------------------------------------------------

/// Entry point for the dedicated worker thread.  Spawns a single-threaded
/// Tokio runtime and processes jobs until the channel is closed or a
/// `Shutdown` message is received.
fn worker_entry(
    receiver: mpsc::Receiver<QueueMessage>,
    semaphore: Arc<Semaphore>,
    state: Arc<WorkerState>,
) {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("failed to build worker Tokio runtime");

    rt.block_on(async move {
        worker_loop(receiver, &semaphore, &state).await;
    });

    info!("queue worker thread exiting");
}

async fn worker_loop(
    mut receiver: mpsc::Receiver<QueueMessage>,
    semaphore: &Arc<Semaphore>,
    state: &Arc<WorkerState>,
) {
    loop {
        let msg = match receiver.recv().await {
            Some(m) => m,
            None => {
                debug!("queue channel closed, worker exiting");
                return;
            }
        };

        match msg {
            QueueMessage::Shutdown { drain_timeout, ack } => {
                info!(
                    drain_timeout_ms = drain_timeout.as_millis() as u64,
                    "queue shutdown requested, draining"
                );
                drain_pending(&mut receiver, semaphore, state, drain_timeout).await;
                let _ = ack.send(());
                return;
            }
            QueueMessage::Job(first_job) => {
                let (jobs, non_job_msgs) = coalesce_jobs(first_job, &mut receiver);

                debug!(job_count = jobs.len(), "processing coalesced job batch");

                execute_job_batch(jobs, semaphore, state).await;

                // Handle any non-job messages drained during coalescing.
                for m in non_job_msgs {
                    if let QueueMessage::Shutdown { drain_timeout, ack } = m {
                        drain_pending(&mut receiver, semaphore, state, drain_timeout).await;
                        let _ = ack.send(());
                        return;
                    }
                }
            }
        }
    }
}

/// Tracks the origin of each request within a flattened batch.
struct RequestEntry {
    job_idx: usize,
    pos_in_job: usize,
    request: ResolvedRequest,
}

/// Execute a batch of jobs, deduplicating requests by `request_id`.
///
/// Within the collected requests, all entries sharing the same `request_id`
/// are executed only once; the result is fanned out to every original caller.
async fn execute_job_batch(jobs: Vec<Job>, semaphore: &Arc<Semaphore>, state: &Arc<WorkerState>) {
    // Flatten all requests, remembering which job/position they came from.
    let mut entries: Vec<RequestEntry> = Vec::new();
    for (job_idx, job) in jobs.iter().enumerate() {
        for (pos, req) in job.requests.iter().enumerate() {
            entries.push(RequestEntry {
                job_idx,
                pos_in_job: pos,
                request: req.clone(),
            });
        }
    }

    // Group by request_id for coalescing.  Only requests that actually carry
    // a `request_id` are eligible for deduplication; those without one get
    // their own synthetic key so they always execute independently.
    let mut groups: HashMap<String, Vec<usize>> = HashMap::new();
    for (idx, entry) in entries.iter().enumerate() {
        let key = match &entry.request.request_id {
            Some(id) if !id.is_empty() => id.clone(),
            _ => format!("__unkeyed_{idx}"),
        };
        groups.entry(key).or_default().push(idx);
    }

    // Execute each unique request_id once, collecting results keyed by
    // flattened index.
    let mut results: HashMap<usize, (Arc<Result<InvokeResult, String>>, Duration)> = HashMap::new();

    let mut join_set = JoinSet::new();
    for indices in groups.into_values() {
        let representative_idx = indices[0];
        let req = entries[representative_idx].request.clone();
        let timeout = jobs[entries[representative_idx].job_idx].timeout;
        let semaphore = Arc::clone(semaphore);
        let state = Arc::clone(state);

        join_set.spawn(async move {
            // Acquire a semaphore permit to bound concurrency.
            let _permit = semaphore.acquire_owned().await.expect("semaphore closed");

            let start = Instant::now();
            let scope_id = req.scope_id.as_deref().unwrap_or("default");
            let agent_key_fallback = req.endpoint_url.clone();
            let agent_key = req.agent_name.as_deref().unwrap_or(&agent_key_fallback);
            let ctx = InvokeContext {
                circuit: &state.circuit,
                metrics: &state.metrics,
                scope_id,
                agent_key,
            };

            let invoke_result = invoke::execute_invoke(
                &state.client,
                &state.config,
                &req.endpoint_url,
                &req.headers,
                &req.json_body,
                timeout,
                Some(&ctx),
            )
            .await;

            (
                indices,
                Arc::new(invoke_result.map_err(|e| e.to_string())),
                start.elapsed(),
            )
        });
    }

    while let Some(joined) = join_set.join_next().await {
        let (indices, shared, elapsed) = joined.expect("queue worker task panicked");
        for idx in indices {
            results.insert(idx, (Arc::clone(&shared), elapsed));
        }
    }

    // Build per-job result vectors and send them back.
    for (job_idx, job) in jobs.into_iter().enumerate() {
        let mut job_results: Vec<JobResult> = Vec::with_capacity(job.requests.len());

        for (pos, req) in job.requests.iter().enumerate() {
            let entry_idx = entries
                .iter()
                .position(|e| e.job_idx == job_idx && e.pos_in_job == pos)
                .expect("entry must exist for every request");

            let (result, duration) = results
                .get(&entry_idx)
                .expect("result must exist for every entry")
                .clone();

            job_results.push(JobResult {
                id: pos,
                result,
                duration,
                agent_name: req.agent_name.clone(),
            });
        }

        if job.result_tx.send(job_results).is_err() {
            warn!("caller dropped result receiver for job {job_idx}");
        }
    }
}

/// Drain remaining messages from the receiver within the given timeout.
async fn drain_pending(
    receiver: &mut mpsc::Receiver<QueueMessage>,
    semaphore: &Arc<Semaphore>,
    state: &Arc<WorkerState>,
    drain_timeout: Duration,
) {
    let deadline = Instant::now() + drain_timeout;

    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            warn!("drain timeout reached, dropping remaining jobs");
            break;
        }

        match tokio::time::timeout(remaining, receiver.recv()).await {
            Ok(Some(QueueMessage::Job(job))) => {
                execute_job_batch(vec![job], semaphore, state).await;
            }
            Ok(Some(QueueMessage::Shutdown { ack, .. })) => {
                // Already shutting down; just acknowledge.
                let _ = ack.send(());
            }
            Ok(None) => break,
            Err(_) => {
                warn!("drain timeout reached, dropping remaining jobs");
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Initialize the queue.  Must be called exactly once before
/// [`try_submit_batch`].
///
/// Spawns a dedicated OS thread with its own single-threaded Tokio runtime.
///
/// * `max_concurrent` — maximum number of concurrent outbound invocations
///   (enforced via a [`Semaphore`]).
/// * `max_queued` — when `Some`, the internal channel is bounded to this
///   capacity; submissions that exceed it fail with [`QueueError::Full`].
///   When `None`, a default bounded capacity is used.
/// * `state` — shared handles for the HTTP client, configuration, circuit
///   breaker, and metrics collector.
pub fn init_queue(max_concurrent: usize, max_queued: Option<usize>, state: Arc<WorkerState>) {
    let semaphore = Arc::new(Semaphore::new(max_concurrent));

    // Build channel and sender variant based on bounding preference.
    let (sender, receiver): (QueueSender, mpsc::Receiver<QueueMessage>) = if let Some(capacity) =
        max_queued
    {
        let (tx, rx) = mpsc::channel(capacity);
        (QueueSender::Bounded(tx), rx)
    } else {
        let (btx, brx) = mpsc::channel::<QueueMessage>(4096);
        warn!(
            "A2A queue running without an explicit bound; falling back to default cap of 4096 messages"
        );
        (QueueSender::Bounded(btx), brx)
    };

    SENDER
        .set(sender)
        .expect("init_queue must be called exactly once");

    std::thread::Builder::new()
        .name("a2a-queue-worker".into())
        .spawn(move || {
            worker_entry(receiver, semaphore, state);
        })
        .expect("failed to spawn queue worker thread");

    info!("queue initialized (max_concurrent={max_concurrent}, max_queued={max_queued:?})");
}

/// Submit a batch of resolved requests for execution.
///
/// Returns a [`oneshot::Receiver`] that will yield the results once the
/// worker has processed the batch.  Fails immediately with
/// [`QueueError::Full`] when the bounded channel is at capacity.
pub fn try_submit_batch(
    requests: Vec<ResolvedRequest>,
    timeout: Duration,
) -> Result<oneshot::Receiver<Vec<JobResult>>, QueueError> {
    if SHUTTING_DOWN.load(Ordering::Acquire) {
        return Err(QueueError::Shutdown);
    }

    let sender = SENDER.get().ok_or(QueueError::NotInitialized)?;

    let (result_tx, result_rx) = oneshot::channel();

    let job = Job {
        requests,
        timeout,
        result_tx,
    };

    sender.try_send(QueueMessage::Job(job))?;

    Ok(result_rx)
}

/// Gracefully shut down the queue, allowing pending jobs to drain within the
/// given timeout.
///
/// After this call returns, subsequent [`try_submit_batch`] calls will fail
/// with [`QueueError::Shutdown`].
pub async fn shutdown_queue(drain_timeout: Duration) {
    SHUTTING_DOWN.store(true, Ordering::Release);

    let sender = match SENDER.get() {
        Some(s) => s,
        None => {
            warn!("shutdown_queue called but queue was never initialized");
            return;
        }
    };

    let (ack_tx, ack_rx) = oneshot::channel();

    let msg = QueueMessage::Shutdown {
        drain_timeout,
        ack: ack_tx,
    };

    if let Err(e) = sender.try_send(msg) {
        error!("failed to send shutdown message: {e}");
        return;
    }

    match tokio::time::timeout(drain_timeout + Duration::from_secs(5), ack_rx).await {
        Ok(Ok(())) => info!("queue shut down gracefully"),
        Ok(Err(_)) => warn!("queue worker dropped shutdown ack"),
        Err(_) => warn!("timed out waiting for queue shutdown ack"),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RuntimeConfig;
    use crate::http::ResolvedRequest;
    use serde_json::json;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn test_runtime_config() -> Arc<RuntimeConfig> {
        Arc::new(RuntimeConfig {
            listen_http: "127.0.0.1:0".to_string(),
            listen_uds: None,
            request_timeout_ms: 1_000,
            client_connect_timeout_ms: 200,
            client_pool_idle_timeout_seconds: 1,
            client_pool_max_idle_per_host: 1,
            client_tcp_keepalive_seconds: 1,
            max_response_body_bytes: 1024 * 1024,
            max_retries: 0,
            retry_backoff_ms: 1,
            auth_secret: None,
            backend_base_url: "http://127.0.0.1:4444".to_string(),
            max_concurrent: 2,
            max_queued: Some(4),
            circuit_failure_threshold: 2,
            circuit_cooldown_secs: 1,
            circuit_max_entries: 8,
            metrics_max_entries: 8,
            agent_cache_ttl_secs: 1,
            agent_cache_max_entries: 8,
            redis_url: None,
            l2_cache_ttl_secs: 1,
            cache_invalidation_channel: "invalidate".to_string(),
            session_enabled: false,
            session_ttl_secs: 1,
            session_fingerprint_headers: "authorization".to_string(),
            event_store_max_events: 8,
            event_store_ttl_secs: 1,
            event_flush_interval_ms: 1,
            event_flush_batch_size: 1,
            uaid_allowed_domains: String::new(),
            uaid_allowed_domains_cache: Default::default(),
            uaid_max_length: 2048,
            uaid_max_federation_hops: 3,
            log_filter: "info".to_string(),
            exit_after_startup_ms: None,
        })
    }

    fn test_worker_state() -> Arc<WorkerState> {
        Arc::new(WorkerState {
            client: Client::new(),
            config: test_runtime_config(),
            circuit: Arc::new(CircuitBreaker::new(2, Duration::from_secs(1), Some(8))),
            metrics: Arc::new(MetricsCollector::new(Some(8))),
        })
    }

    #[test]
    fn queue_error_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<QueueError>();
    }

    #[test]
    fn job_result_is_send() {
        fn assert_send<T: Send>() {}
        assert_send::<JobResult>();
    }

    #[test]
    fn job_result_clone_shares_arc() {
        let result = Arc::new(Ok(InvokeResult {
            status_code: 200,
            headers: HashMap::new(),
            json: None,
            text: "ok".into(),
        }));
        let jr = JobResult {
            id: 0,
            result: Arc::clone(&result),
            duration: Duration::from_millis(42),
            agent_name: Some("test".into()),
        };
        let jr2 = jr.clone();
        assert!(Arc::ptr_eq(&jr.result, &jr2.result));
    }

    #[test]
    fn queue_error_display() {
        assert_eq!(QueueError::Full.to_string(), "queue is full");
        assert_eq!(
            QueueError::NotInitialized.to_string(),
            "queue not initialized"
        );
        assert_eq!(QueueError::Shutdown.to_string(), "queue is shutting down");
    }

    #[test]
    fn try_submit_batch_rejects_when_queue_not_initialized() {
        let err = try_submit_batch(vec![], Duration::from_millis(10)).expect_err("should reject");
        assert!(matches!(
            err,
            QueueError::NotInitialized | QueueError::Shutdown
        ));
    }

    #[tokio::test]
    async fn coalesce_jobs_collects_follow_on_jobs_and_preserves_shutdown() {
        let (tx, mut rx) = mpsc::channel(4);
        let (result_tx_first, _result_rx_first) = oneshot::channel();
        let (result_tx_second, _result_rx_second) = oneshot::channel();
        let (ack_tx, _ack_rx) = oneshot::channel();

        let first = Job {
            requests: vec![],
            timeout: Duration::from_secs(1),
            result_tx: result_tx_first,
        };

        tx.send(QueueMessage::Job(Job {
            requests: vec![],
            timeout: Duration::from_secs(1),
            result_tx: result_tx_second,
        }))
        .await
        .unwrap();
        tx.send(QueueMessage::Shutdown {
            drain_timeout: Duration::from_secs(1),
            ack: ack_tx,
        })
        .await
        .unwrap();

        let (jobs, non_job_messages) = coalesce_jobs(first, &mut rx);
        assert_eq!(jobs.len(), 2);
        assert_eq!(non_job_messages.len(), 1);
        assert!(matches!(
            non_job_messages.into_iter().next(),
            Some(QueueMessage::Shutdown { .. })
        ));
    }

    #[tokio::test]
    async fn execute_job_batch_deduplicates_requests_by_request_id() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/invoke"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
            .expect(2)
            .mount(&mock_server)
            .await;

        let (tx_a, rx_a) = oneshot::channel();
        let (tx_b, rx_b) = oneshot::channel();
        let job_a = Job {
            requests: vec![
                ResolvedRequest {
                    id: 0,
                    endpoint_url: format!("{}/invoke", mock_server.uri()),
                    headers: HashMap::new(),
                    json_body: json!({"id": 1}),
                    timeout_seconds: None,
                    agent_name: Some("agent-a".to_string()),
                    agent_id: None,
                    interaction_type: None,
                    scope_id: Some("scope-1".to_string()),
                    request_id: Some("dedupe-me".to_string()),
                    correlation_id: None,
                },
                ResolvedRequest {
                    id: 1,
                    endpoint_url: format!("{}/invoke", mock_server.uri()),
                    headers: HashMap::new(),
                    json_body: json!({"id": 2}),
                    timeout_seconds: None,
                    agent_name: Some("agent-b".to_string()),
                    agent_id: None,
                    interaction_type: None,
                    scope_id: Some("scope-1".to_string()),
                    request_id: None,
                    correlation_id: None,
                },
            ],
            timeout: Duration::from_secs(1),
            result_tx: tx_a,
        };
        let job_b = Job {
            requests: vec![ResolvedRequest {
                id: 0,
                endpoint_url: format!("{}/invoke", mock_server.uri()),
                headers: HashMap::new(),
                json_body: json!({"id": 3}),
                timeout_seconds: None,
                agent_name: Some("agent-a".to_string()),
                agent_id: None,
                interaction_type: None,
                scope_id: Some("scope-1".to_string()),
                request_id: Some("dedupe-me".to_string()),
                correlation_id: None,
            }],
            timeout: Duration::from_secs(1),
            result_tx: tx_b,
        };

        execute_job_batch(
            vec![job_a, job_b],
            &Arc::new(Semaphore::new(4)),
            &test_worker_state(),
        )
        .await;

        let results_a = rx_a.await.unwrap();
        let results_b = rx_b.await.unwrap();
        assert_eq!(results_a.len(), 2);
        assert_eq!(results_b.len(), 1);
        assert!(results_a[0].result.as_ref().is_ok());
        assert!(results_a[1].result.as_ref().is_ok());
        assert!(results_b[0].result.as_ref().is_ok());
        mock_server.verify().await;
    }

    #[test]
    fn queue_sender_try_send_maps_full_and_closed() {
        let (tx, mut rx) = mpsc::channel(1);
        let sender = QueueSender::Bounded(tx);
        let (result_tx_one, _result_rx_one) = oneshot::channel();
        let (result_tx_two, _result_rx_two) = oneshot::channel();

        sender
            .try_send(QueueMessage::Job(Job {
                requests: vec![],
                timeout: Duration::from_secs(1),
                result_tx: result_tx_one,
            }))
            .unwrap();

        let err = sender
            .try_send(QueueMessage::Job(Job {
                requests: vec![],
                timeout: Duration::from_secs(1),
                result_tx: result_tx_two,
            }))
            .unwrap_err();
        assert!(matches!(err, QueueError::Full));

        drop(rx.try_recv());
        drop(rx);
        let (ack_tx, _ack_rx) = oneshot::channel();
        let err = sender
            .try_send(QueueMessage::Shutdown {
                drain_timeout: Duration::from_secs(1),
                ack: ack_tx,
            })
            .unwrap_err();
        assert!(matches!(err, QueueError::Shutdown));
    }

    #[tokio::test]
    async fn worker_loop_returns_when_channel_is_closed() {
        let (tx, rx) = mpsc::channel(1);
        drop(tx);
        worker_loop(rx, &Arc::new(Semaphore::new(1)), &test_worker_state()).await;
    }

    #[tokio::test]
    async fn try_send_rejects_overflow_under_concurrent_producers() {
        // Multiple producers racing to submit into a bounded channel must
        // get QueueError::Full once capacity is exhausted — rather than
        // blocking or dropping messages silently.  This verifies the
        // semaphore-bounded contract under producer contention.
        let (tx, mut rx) = mpsc::channel(4);
        let sender = Arc::new(QueueSender::Bounded(tx));

        let mut handles = Vec::new();
        for _ in 0..16 {
            let sender_clone = Arc::clone(&sender);
            handles.push(tokio::spawn(async move {
                let (result_tx, _result_rx) = oneshot::channel();
                sender_clone.try_send(QueueMessage::Job(Job {
                    requests: vec![],
                    timeout: Duration::from_secs(1),
                    result_tx,
                }))
            }));
        }

        let mut ok_count = 0;
        let mut full_count = 0;
        for h in handles {
            match h.await.expect("task join") {
                Ok(()) => ok_count += 1,
                Err(QueueError::Full) => full_count += 1,
                Err(other) => panic!("unexpected error: {other:?}"),
            }
        }

        assert_eq!(ok_count, 4, "exactly capacity-many sends succeed");
        assert_eq!(full_count, 12, "remainder reject with Full");

        // Drain the channel so the test does not leak pending messages.
        while rx.try_recv().is_ok() {}
    }

    #[tokio::test]
    async fn worker_loop_acknowledges_shutdown() {
        let (tx, rx) = mpsc::channel(2);
        let (ack_tx, ack_rx) = oneshot::channel();

        tx.send(QueueMessage::Shutdown {
            drain_timeout: Duration::from_millis(1),
            ack: ack_tx,
        })
        .await
        .unwrap();
        drop(tx);

        worker_loop(rx, &Arc::new(Semaphore::new(1)), &test_worker_state()).await;

        ack_rx.await.unwrap();
    }

    #[tokio::test]
    async fn drain_pending_processes_jobs_and_acknowledges_shutdown() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/invoke"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
            .mount(&mock_server)
            .await;

        let (tx, mut rx) = mpsc::channel(4);
        let (result_tx, result_rx) = oneshot::channel();
        tx.send(QueueMessage::Job(Job {
            requests: vec![ResolvedRequest {
                id: 0,
                endpoint_url: format!("{}/invoke", mock_server.uri()),
                headers: HashMap::new(),
                json_body: json!({"id": 1}),
                timeout_seconds: None,
                agent_name: Some("agent-a".to_string()),
                agent_id: None,
                interaction_type: None,
                scope_id: Some("scope-1".to_string()),
                request_id: None,
                correlation_id: None,
            }],
            timeout: Duration::from_secs(1),
            result_tx,
        }))
        .await
        .unwrap();

        let (ack_tx, ack_rx) = oneshot::channel();
        tx.send(QueueMessage::Shutdown {
            drain_timeout: Duration::from_secs(1),
            ack: ack_tx,
        })
        .await
        .unwrap();
        drop(tx);

        drain_pending(
            &mut rx,
            &Arc::new(Semaphore::new(1)),
            &test_worker_state(),
            Duration::from_secs(1),
        )
        .await;

        assert!(result_rx.await.unwrap()[0].result.as_ref().is_ok());
        ack_rx.await.unwrap();
    }

    #[tokio::test]
    async fn execute_job_batch_tolerates_dropped_result_receiver() {
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/invoke"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
            .mount(&mock_server)
            .await;

        let (tx, rx) = oneshot::channel();
        drop(rx);

        execute_job_batch(
            vec![Job {
                requests: vec![ResolvedRequest {
                    id: 0,
                    endpoint_url: format!("{}/invoke", mock_server.uri()),
                    headers: HashMap::new(),
                    json_body: json!({"id": 1}),
                    timeout_seconds: None,
                    agent_name: Some("agent-a".to_string()),
                    agent_id: None,
                    interaction_type: None,
                    scope_id: Some("scope-1".to_string()),
                    request_id: None,
                    correlation_id: None,
                }],
                timeout: Duration::from_secs(1),
                result_tx: tx,
            }],
            &Arc::new(Semaphore::new(1)),
            &test_worker_state(),
        )
        .await;
    }
}
