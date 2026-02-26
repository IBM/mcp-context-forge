// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// A2A invoke queue: bounded concurrency, FIFO. Jobs are Python callables run with GIL.
// Up to max_concurrent worker threads run jobs in parallel.

use std::collections::VecDeque;
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::thread;

use pyo3::prelude::*;
use tokio::sync::oneshot;

type Job = (Py<PyAny>, oneshot::Sender<PyResult<Py<PyAny>>>);

struct QueueState {
    tx: mpsc::Sender<Job>,
    _worker_joins: Vec<thread::JoinHandle<()>>,
}

static QUEUE_STATE: OnceLock<QueueState> = OnceLock::new();

/// Initialize the A2A invoke queue. Must be called once at startup with max concurrent tasks.
/// Safe to call from Python with the same value multiple times (first call wins).
#[pyfunction]
pub fn init_queue(max_concurrent: usize) -> PyResult<()> {
    QUEUE_STATE.get_or_init(|| {
        let (tx, rx) = mpsc::channel::<Job>();
        let jobs: Arc<Mutex<VecDeque<Job>>> = Arc::new(Mutex::new(VecDeque::new()));
        let not_empty: Arc<Condvar> = Arc::new(Condvar::new());
        let available: Arc<(Mutex<usize>, Condvar)> = Arc::new((Mutex::new(max_concurrent), Condvar::new()));

        let feeder_jobs = Arc::clone(&jobs);
        let feeder_not_empty = Arc::clone(&not_empty);
        thread::spawn(move || {
            while let Ok(job) = rx.recv() {
                let mut g = feeder_jobs.lock().unwrap();
                g.push_back(job);
                feeder_not_empty.notify_one();
            }
        });

        let mut worker_joins = Vec::with_capacity(max_concurrent);
        for _ in 0..max_concurrent {
            let jobs_w = Arc::clone(&jobs);
            let not_empty_w = Arc::clone(&not_empty);
            let available_w = Arc::clone(&available);
            let handle = thread::spawn(move || {
                loop {
                    let (avail_mutex, avail_cv) = &*available_w;
                    {
                        let mut g = avail_mutex.lock().unwrap();
                        while *g == 0 {
                            g = avail_cv.wait(g).unwrap();
                        }
                        *g -= 1;
                    }
                    let job = {
                        let mut g = jobs_w.lock().unwrap();
                        while g.is_empty() {
                            g = not_empty_w.wait(g).unwrap();
                        }
                        g.pop_front().unwrap()
                    };
                    let result = Python::attach(|py| job.0.call0(py));
                    let _ = job.1.send(result);
                    {
                        let (avail_mutex, avail_cv) = &*available_w;
                        let mut g = avail_mutex.lock().unwrap();
                        *g += 1;
                        avail_cv.notify_one();
                    }
                }
            });
            worker_joins.push(handle);
        }

        QueueState {
            tx,
            _worker_joins: worker_joins,
        }
    });
    Ok(())
}

/// Submit a job (no-arg Python callable) to the queue. Returns an awaitable that resolves with the callable's return value.
/// The callable is run when a worker slot is free (FIFO). Requires init_queue to have been called first.
#[pyfunction]
pub fn submit_queue<'py>(
    py: Python<'py>,
    callable: Bound<'py, PyAny>,
    max_concurrent: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let state = QUEUE_STATE.get().ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err(
            "A2A invoke queue not initialized; call init_queue(max_concurrent) first",
        )
    })?;
    let (tx, rx) = oneshot::channel();
    let callable: Py<PyAny> = callable.unbind();
    state
        .tx
        .send((callable, tx))
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    let _ = max_concurrent;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = rx.await.map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("queue response channel closed: {}", e))
        })?;
        result
    })
}

#[cfg(test)]
mod tests {
    // Queue tests would require Python interpreter; leave for integration tests.
}
