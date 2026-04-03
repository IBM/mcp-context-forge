// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Async Unix-domain-socket validation sidecar.

pub mod protocol;
pub mod validator;

use crate::protocol::{
    ProtocolError, ValidationRequestEnvelope, ValidationResponseEnvelope, invalid_envelope,
    read_frame, write_json_frame,
};
use crate::validator::{ParserBackend, validate_request};
use std::{future::Future, path::PathBuf, sync::Arc};
use thiserror::Error;
use tokio::net::{UnixListener, UnixStream};

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub uds_path: PathBuf,
    pub parser_backend: ParserBackend,
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
    if let Some(parent) = config.uds_path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    if config.uds_path.exists() {
        let _ = tokio::fs::remove_file(&config.uds_path).await;
    }

    let listener = UnixListener::bind(&config.uds_path)?;
    let uds_path = config.uds_path.clone();
    let result = serve_until(listener, config.parser_backend, async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await;

    let _ = tokio::fs::remove_file(uds_path).await;
    result
}

pub async fn serve_until<F>(
    listener: UnixListener,
    parser_backend: ParserBackend,
    shutdown: F,
) -> Result<(), SidecarError>
where
    F: Future<Output = ()> + Send,
{
    let parser_backend = Arc::new(parser_backend);
    tokio::pin!(shutdown);

    loop {
        tokio::select! {
            _ = &mut shutdown => return Ok(()),
            accept_result = listener.accept() => {
                let (stream, _) = accept_result?;
                let parser_backend = Arc::clone(&parser_backend);
                tokio::spawn(async move {
                    if let Err(err) = handle_connection(stream, *parser_backend).await {
                        eprintln!("validation sidecar connection failed: {err}");
                    }
                });
            }
        }
    }
}

async fn handle_connection(
    mut stream: UnixStream,
    parser_backend: ParserBackend,
) -> Result<(), SidecarError> {
    loop {
        let payload = match read_frame(&mut stream).await {
            Ok(payload) => payload,
            Err(ProtocolError::Io(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {
                return Ok(());
            }
            Err(error) => return Err(error.into()),
        };

        let envelope: ValidationRequestEnvelope =
            serde_json::from_slice(&payload).map_err(ProtocolError::from)?;
        let request = envelope.into_request()?;
        let response = if request.healthcheck {
            ValidationResponseEnvelope::ok()
        } else {
            match validate_request(&request, parser_backend)? {
                Some(rejection) => ValidationResponseEnvelope::rejected(
                    rejection.key,
                    rejection.error_type,
                    rejection.detail,
                ),
                None => ValidationResponseEnvelope::ok(),
            }
        };

        let response = response
            .validate()
            .map_err(|_| invalid_envelope("sidecar built an invalid response"))?;
        write_json_frame(&mut stream, &response).await?;
    }
}
