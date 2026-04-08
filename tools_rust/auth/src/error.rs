// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use thiserror::Error;

#[derive(Debug, Error)]
pub enum SidecarError {
    #[error("config error: {0}")]
    Config(String),
    #[error("backend readiness check failed: {0}")]
    BackendReadiness(String),
    #[error("http client error: {0}")]
    HttpClient(#[from] reqwest::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}
