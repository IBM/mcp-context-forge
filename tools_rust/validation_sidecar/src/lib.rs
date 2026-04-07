// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Async Unix-domain-socket validation sidecar.

pub mod protocol;
pub mod validator;

use crate::protocol::{
    ProtocolError, ValidationResponseEnvelope, decode_request_payload, invalid_envelope,
    read_frame, write_json_frame, write_ok_frame,
};
use crate::validator::{ValidatorError, validate_request};
use std::{future::Future, os::unix::fs::PermissionsExt, path::PathBuf, sync::Arc, time::Duration};
use thiserror::Error;
use tokio::{
    net::{UnixListener, UnixStream},
    sync::{OwnedSemaphorePermit, Semaphore, watch},
    time::timeout,
};

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub uds_path: PathBuf,
    pub connection_idle_timeout: Duration,
    pub max_connections: usize,
}

impl ServerConfig {
    pub fn new(uds_path: PathBuf) -> Self {
        Self {
            uds_path,
            connection_idle_timeout: Duration::from_secs(5),
            max_connections: 256,
        }
    }
}

#[derive(Debug, Error)]
pub enum SidecarError {
    #[error("{0}")]
    Protocol(#[from] ProtocolError),
    #[error("{0}")]
    Validator(#[from] validator::ValidatorError),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub async fn run(config: ServerConfig) -> Result<(), SidecarError> {
    let listener = prepare_listener(&config).await?;
    let uds_path = config.uds_path.clone();
    let result = serve_until(listener, config, async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await;

    let _ = std::fs::remove_file(uds_path);
    result
}

pub async fn prepare_listener(config: &ServerConfig) -> Result<UnixListener, SidecarError> {
    if let Some(parent) = config.uds_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if config.uds_path.exists() {
        let _ = std::fs::remove_file(&config.uds_path);
    }

    let listener = UnixListener::bind(&config.uds_path)?;
    std::fs::set_permissions(&config.uds_path, std::fs::Permissions::from_mode(0o600))?;
    Ok(listener)
}

pub async fn serve_until<F>(
    listener: UnixListener,
    config: ServerConfig,
    shutdown: F,
) -> Result<(), SidecarError>
where
    F: Future<Output = ()> + Send,
{
    tokio::pin!(shutdown);
    let semaphore = Arc::new(Semaphore::new(config.max_connections.max(1)));
    let (shutdown_tx, shutdown_rx) = watch::channel(false);

    loop {
        tokio::select! {
            _ = &mut shutdown => {
                let _ = shutdown_tx.send(true);
                return Ok(());
            },
            accept_result = listener.accept() => {
                let (stream, _) = accept_result?;
                let semaphore = semaphore.clone();
                let idle_timeout = config.connection_idle_timeout;
                let shutdown_rx = shutdown_rx.clone();
                tokio::spawn(async move {
                    let Some(_permit) = acquire_connection_permit(semaphore, shutdown_rx.clone()).await else {
                        return;
                    };
                    if let Err(err) = handle_connection(stream, idle_timeout, shutdown_rx).await {
                        eprintln!("validation sidecar connection failed: {err}");
                    }
                });
            }
        }
    }
}

async fn acquire_connection_permit(
    semaphore: Arc<Semaphore>,
    mut shutdown_rx: watch::Receiver<bool>,
) -> Option<OwnedSemaphorePermit> {
    tokio::select! {
        permit = semaphore.acquire_owned() => Some(permit.expect("validation sidecar semaphore closed")),
        _ = shutdown_rx.changed() => None,
    }
}

async fn handle_connection(
    mut stream: UnixStream,
    idle_timeout: Duration,
    mut shutdown_rx: watch::Receiver<bool>,
) -> Result<(), SidecarError> {
    loop {
        let payload = match tokio::select! {
            result = timeout(idle_timeout, read_frame(&mut stream)) => result,
            _ = shutdown_rx.changed() => return Ok(()),
        } {
            Ok(Ok(payload)) => payload,
            Ok(Err(ProtocolError::Io(error)))
                if error.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                return Ok(());
            }
            Ok(Err(error)) => return Err(error.into()),
            Err(_) => return Ok(()),
        };

        let request = decode_request_payload(payload)?;
        if request.healthcheck {
            match validate_request(&request) {
                Ok(_) => write_ok_frame(&mut stream).await?,
                Err(ValidatorError::InvalidRegex(error)) => {
                    let response = ValidationResponseEnvelope::rejected(
                        "dangerous_patterns",
                        "invalid_pattern",
                        format!("dangerous pattern regex is not supported by Rust regex: {error}"),
                    )
                    .validate()
                    .map_err(|_| invalid_envelope("sidecar built an invalid response"))?;
                    write_json_frame(&mut stream, &response).await?;
                }
                Err(error) => return Err(error.into()),
            }
            continue;
        }

        let response = match validate_request(&request)? {
            Some(rejection) => ValidationResponseEnvelope::rejected(
                rejection.key,
                rejection.error_type,
                rejection.detail,
            ),
            None => {
                write_ok_frame(&mut stream).await?;
                continue;
            }
        };

        let response = response
            .validate()
            .map_err(|_| invalid_envelope("sidecar built an invalid response"))?;
        write_json_frame(&mut stream, &response).await?;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn shutdown_cancels_waiting_connection_permit() {
        let semaphore = Arc::new(Semaphore::new(1));
        let held_permit = semaphore
            .clone()
            .acquire_owned()
            .await
            .expect("initial permit");
        let (shutdown_tx, shutdown_rx) = watch::channel(false);

        let waiter = tokio::spawn(acquire_connection_permit(semaphore, shutdown_rx));
        shutdown_tx.send(true).expect("send shutdown");

        let permit = timeout(Duration::from_millis(200), waiter)
            .await
            .expect("permit wait should stop on shutdown")
            .expect("join handle");

        drop(held_permit);

        assert!(permit.is_none());
    }
}
