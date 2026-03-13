// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! A2A invoke batch queue: bounded concurrency and optional bounded depth.
//!
//! Jobs are HTTP batch payloads `(Vec<A2AInvokeRequest>, Duration)` submitted via
//! [`try_submit_batch`]. A dedicated thread runs a Tokio runtime; up to `max_concurrent`
//! batches run in parallel. When `max_queued` is set, the channel is bounded and
//! try_submit returns `Err(QueueError::Full)` when full so Python can return 503.
//! When `max_queued` is None, the channel is unbounded.
//! Graceful shutdown: call [`shutdown_queue`] (async) to stop accepting new work and
//! drain pending jobs with a timeout.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use log::info;
use tokio::runtime::Runtime;
use tokio::sync::{Semaphore, mpsc, oneshot};
use tokio::task::JoinSet;
use tokio::time::Instant;

use crate::invoker::{A2AInvokeRequest, A2AInvokeResult};

/// A single batch job: requests, timeout, and oneshot to send results back.
struct Job {
    requests: Vec<A2AInvokeRequest>,
    timeout: Duration,
    result_tx: oneshot::Sender<Vec<A2AInvokeResult>>,
}

const MAX_COALESCED_REQUESTS: usize = 128;

/// Run one job group: acquire permit once, invoke once, then fan results back to the original submitters.
async fn run_job_group(jobs: Vec<Job>, semaphore: Arc<Semaphore>) {
    let _permit = semaphore.acquire_owned().await;
    let inv = crate::get_invoker();
    let timeout = jobs.first().map(|job| job.timeout).unwrap_or_default();
    let mut all_requests = Vec::new();
    let mut result_channels = Vec::with_capacity(jobs.len());
    let mut request_counts = Vec::with_capacity(jobs.len());
    let mut original_ids_per_job = Vec::with_capacity(jobs.len());
    let mut next_request_id = 0;
    for mut job in jobs {
        let original_ids: Vec<usize> = job.requests.iter().map(|request| request.id).collect();
        for request in &mut job.requests {
            request.id = next_request_id;
            next_request_id += 1;
        }
        request_counts.push(job.requests.len());
        original_ids_per_job.push(original_ids);
        result_channels.push(job.result_tx);
        all_requests.extend(job.requests);
    }
    let results = inv.invoke(all_requests, timeout).await;
    drop(_permit);
    let mut cursor = 0;
    for ((request_count, result_tx), original_ids) in request_counts
        .into_iter()
        .zip(result_channels.into_iter())
        .zip(original_ids_per_job.into_iter())
    {
        let end = cursor + request_count;
        let mut job_results = results[cursor..end].to_vec();
        for (result, original_id) in job_results.iter_mut().zip(original_ids.into_iter()) {
            result.id = original_id;
        }
        let _ = result_tx.send(job_results);
        cursor = end;
    }
}

struct ShutdownRequest {
    ack: oneshot::Sender<()>,
    drain_timeout: Duration,
}

fn coalesce_job(
    first_job: Job,
    pending_jobs: &mut VecDeque<Job>,
    rx: &mut QueueReceiver,
    pending_shutdown: &mut Option<ShutdownRequest>,
) -> Vec<Job> {
    let target_timeout = first_job.timeout;
    let mut jobs = vec![first_job];
    let mut total_requests = jobs[0].requests.len();

    let mut remaining_pending = VecDeque::new();
    while let Some(job) = pending_jobs.pop_front() {
        let job_request_count = job.requests.len();
        if job.timeout == target_timeout
            && total_requests + job_request_count <= MAX_COALESCED_REQUESTS
        {
            total_requests += job_request_count;
            jobs.push(job);
            if total_requests >= MAX_COALESCED_REQUESTS {
                break;
            }
        } else {
            remaining_pending.push_back(job);
        }
    }
    while let Some(job) = pending_jobs.pop_front() {
        remaining_pending.push_back(job);
    }
    *pending_jobs = remaining_pending;

    while total_requests < MAX_COALESCED_REQUESTS {
        match rx.try_recv() {
            Ok(QueueMessage::Job(job)) => {
                let job_request_count = job.requests.len();
                if job.timeout == target_timeout
                    && total_requests + job_request_count <= MAX_COALESCED_REQUESTS
                {
                    total_requests += job_request_count;
                    jobs.push(job);
                } else {
                    pending_jobs.push_back(job);
                }
            }
            Ok(QueueMessage::Shutdown { ack, drain_timeout }) => {
                *pending_shutdown = Some(ShutdownRequest { ack, drain_timeout });
                break;
            }
            Err(QueueTryRecvError::Empty) | Err(QueueTryRecvError::Disconnected) => break,
        }
    }

    jobs
}

/// Message to the queue worker: either a job or a shutdown request with ack and drain timeout.
enum QueueMessage {
    Job(Job),
    Shutdown {
        ack: oneshot::Sender<()>,
        drain_timeout: Duration,
    },
}

/// Error when the queue cannot accept new work.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueueError {
    /// Queue is at capacity (max_queued exceeded).
    Full,
    /// Queue was not initialized.
    NotInitialized,
    /// Queue is shutting down or channel closed.
    Shutdown,
}

enum QueueSender {
    Bounded(mpsc::Sender<QueueMessage>),
    Unbounded(mpsc::UnboundedSender<QueueMessage>),
}

impl Clone for QueueSender {
    fn clone(&self) -> Self {
        match self {
            QueueSender::Bounded(tx) => QueueSender::Bounded(tx.clone()),
            QueueSender::Unbounded(tx) => QueueSender::Unbounded(tx.clone()),
        }
    }
}

static QUEUE_STATE: OnceLock<QueueSender> = OnceLock::new();
static SHUTDOWN_REQUESTED: AtomicBool = AtomicBool::new(false);
/// When set, Python passes encrypted auth blobs only; Rust is the only decryption path (AES-GCM match services_auth). No Python fallback.
static AUTH_SECRET: OnceLock<Option<String>> = OnceLock::new();

/// Returns the auth encryption secret if set at init; when Some, request tuples carry encrypted auth and we decrypt.
/// When None (env var unset), the same parse path is used and request tuples carry plain auth; no decryption.
pub fn get_auth_secret() -> Option<&'static str> {
    AUTH_SECRET.get().and_then(|o| o.as_deref())
}

/// Initialize the A2A invoke batch queue. Call once at startup.
/// * `max_concurrent`: max batches in flight (worker semaphore).
/// * `max_queued`: max pending jobs in the channel; when exceeded try_submit_batch returns QueueError::Full. None = unbounded.
/// * `auth_secret`: when Some, request tuples must carry encrypted auth (query params and headers); we decrypt in Rust.
#[allow(clippy::module_name_repetitions)]
pub fn init_queue(max_concurrent: usize, max_queued: Option<usize>, auth_secret: Option<String>) {
    let _ = AUTH_SECRET.set(auth_secret);
    let _ = QUEUE_STATE.get_or_init(|| {
        SHUTDOWN_REQUESTED.store(false, Ordering::SeqCst);
        let (sender, mut rx) = match max_queued {
            Some(capacity) => {
                let (tx, rx) = mpsc::channel::<QueueMessage>(capacity);
                (QueueSender::Bounded(tx), QueueReceiver::Bounded(rx))
            }
            None => {
                let (tx, rx) = mpsc::unbounded_channel::<QueueMessage>();
                (QueueSender::Unbounded(tx), QueueReceiver::Unbounded(rx))
            }
        };
        info!(
            "A2A invoke queue: max_concurrent={}, max_queued={:?}",
            max_concurrent, max_queued
        );
        thread::spawn(move || {
            let rt = Runtime::new().expect("A2A queue Tokio runtime");
            rt.block_on(async {
                let semaphore = Arc::new(Semaphore::new(max_concurrent));
                let mut joinset: JoinSet<()> = JoinSet::new();
                let mut pending_jobs: VecDeque<Job> = VecDeque::new();
                let mut pending_shutdown: Option<ShutdownRequest> = None;
                loop {
                    let next_message = if let Some(shutdown) = pending_shutdown.take() {
                        Some(QueueMessage::Shutdown {
                            ack: shutdown.ack,
                            drain_timeout: shutdown.drain_timeout,
                        })
                    } else if let Some(job) = pending_jobs.pop_front() {
                        Some(QueueMessage::Job(job))
                    } else {
                        rx.recv().await
                    };
                    match next_message {
                        Some(QueueMessage::Job(job)) => {
                            let jobs = coalesce_job(
                                job,
                                &mut pending_jobs,
                                &mut rx,
                                &mut pending_shutdown,
                            );
                            let sem = semaphore.clone();
                            joinset.spawn(async move {
                                run_job_group(jobs, sem).await;
                            });
                        }
                        Some(QueueMessage::Shutdown { ack, drain_timeout }) => {
                            let deadline = Instant::now() + drain_timeout;
                            while let Some(job) = pending_jobs.pop_front() {
                                let jobs = coalesce_job(
                                    job,
                                    &mut pending_jobs,
                                    &mut rx,
                                    &mut pending_shutdown,
                                );
                                let sem = semaphore.clone();
                                joinset.spawn(async move {
                                    run_job_group(jobs, sem).await;
                                });
                            }
                            while Instant::now() < deadline {
                                match rx.try_recv() {
                                    Ok(QueueMessage::Job(job)) => {
                                        let jobs = coalesce_job(
                                            job,
                                            &mut pending_jobs,
                                            &mut rx,
                                            &mut pending_shutdown,
                                        );
                                        let sem = semaphore.clone();
                                        joinset.spawn(async move {
                                            run_job_group(jobs, sem).await;
                                        });
                                    }
                                    Ok(QueueMessage::Shutdown {
                                        ack: _,
                                        drain_timeout: _,
                                    }) => {}
                                    Err(QueueTryRecvError::Empty) => break,
                                    Err(QueueTryRecvError::Disconnected) => break,
                                }
                            }
                            // Wait for in-flight jobs to finish (best effort within drain_timeout).
                            while Instant::now() < deadline {
                                let remaining = deadline.saturating_duration_since(Instant::now());
                                if remaining.is_zero() {
                                    break;
                                }
                                match tokio::time::timeout(remaining, joinset.join_next()).await {
                                    Ok(Some(_)) => continue,
                                    Ok(None) => break,
                                    Err(_) => break,
                                }
                            }
                            let _ = ack.send(());
                            break;
                        }
                        None => break,
                    }
                }
            });
        });
        sender
    });
}

/// Submit a batch to the queue. Returns a receiver for the result, or QueueError if the queue is unavailable.
/// Requires [`init_queue`] to have been called first.
#[allow(clippy::module_name_repetitions)]
pub fn try_submit_batch(
    requests: Vec<A2AInvokeRequest>,
    timeout: Duration,
) -> Result<oneshot::Receiver<Vec<A2AInvokeResult>>, QueueError> {
    if SHUTDOWN_REQUESTED.load(Ordering::SeqCst) {
        return Err(QueueError::Shutdown);
    }
    let tx = QUEUE_STATE.get().ok_or(QueueError::NotInitialized)?.clone();
    let (result_tx, result_rx) = oneshot::channel();
    let msg = QueueMessage::Job(Job {
        requests,
        timeout,
        result_tx,
    });
    match tx {
        QueueSender::Bounded(tx) => tx.try_send(msg).map_err(|e| match e {
            mpsc::error::TrySendError::Full(_) => QueueError::Full,
            mpsc::error::TrySendError::Closed(_) => QueueError::Shutdown,
        })?,
        QueueSender::Unbounded(tx) => tx.send(msg).map_err(|_| QueueError::Shutdown)?,
    }
    Ok(result_rx)
}

/// Graceful shutdown: signal the worker to stop accepting new work and drain pending jobs, then wait for ack (or timeout).
/// Call this from Python's lifespan after stopping the metrics buffer; await with the desired timeout.
/// After this returns, [`try_submit_batch`] will return `Err(QueueError::Shutdown)`.
pub async fn shutdown_queue(timeout_secs: f64) -> Result<(), String> {
    let tx = QUEUE_STATE
        .get()
        .ok_or_else(|| "A2A invoke queue was not initialized".to_string())?
        .clone();
    SHUTDOWN_REQUESTED.store(true, Ordering::SeqCst);
    let drain_timeout = Duration::from_secs_f64(timeout_secs);
    let (ack_tx, ack_rx) = oneshot::channel();
    match tx {
        QueueSender::Bounded(tx) => {
            tx.send(QueueMessage::Shutdown {
                ack: ack_tx,
                drain_timeout,
            })
            .await
            .map_err(|e| format!("queue worker channel closed: {}", e))?;
        }
        QueueSender::Unbounded(tx) => {
            tx.send(QueueMessage::Shutdown {
                ack: ack_tx,
                drain_timeout,
            })
            .map_err(|e| format!("queue worker channel closed: {}", e))?;
        }
    }
    let wait_timeout = Duration::from_secs_f64(timeout_secs + 5.0);
    tokio::time::timeout(wait_timeout, ack_rx)
        .await
        .map_err(|_| "queue shutdown ack timed out".to_string())?
        .map_err(|_| "queue shutdown ack channel closed".to_string())?;
    Ok(())
}

enum QueueReceiver {
    Bounded(mpsc::Receiver<QueueMessage>),
    Unbounded(mpsc::UnboundedReceiver<QueueMessage>),
}

impl QueueReceiver {
    async fn recv(&mut self) -> Option<QueueMessage> {
        match self {
            QueueReceiver::Bounded(rx) => rx.recv().await,
            QueueReceiver::Unbounded(rx) => rx.recv().await,
        }
    }

    fn try_recv(&mut self) -> Result<QueueMessage, QueueTryRecvError> {
        match self {
            QueueReceiver::Bounded(rx) => match rx.try_recv() {
                Ok(msg) => Ok(msg),
                Err(mpsc::error::TryRecvError::Empty) => Err(QueueTryRecvError::Empty),
                Err(mpsc::error::TryRecvError::Disconnected) => {
                    Err(QueueTryRecvError::Disconnected)
                }
            },
            QueueReceiver::Unbounded(rx) => match rx.try_recv() {
                Ok(msg) => Ok(msg),
                Err(mpsc::error::TryRecvError::Empty) => Err(QueueTryRecvError::Empty),
                Err(mpsc::error::TryRecvError::Disconnected) => {
                    Err(QueueTryRecvError::Disconnected)
                }
            },
        }
    }
}

enum QueueTryRecvError {
    Empty,
    Disconnected,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_queue_full_is_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<QueueError>();
    }
}
