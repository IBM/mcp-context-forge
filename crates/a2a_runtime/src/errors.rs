// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Typed error model for outbound A2A invocations.

use axum::http::StatusCode;
use std::time::Duration;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum InvokeError {
    #[error("request to agent timed out after {:.1}s", .0.as_secs_f64())]
    Timeout(Duration),

    #[error("connection to agent failed: {0}")]
    Connection(String),

    #[error("agent returned HTTP {0}")]
    AgentHttp(u16),

    #[error("response body exceeds {limit} byte limit")]
    OversizedResponse { limit: u64 },

    #[error("circuit breaker is open for this endpoint")]
    CircuitOpen,

    #[error("auth decryption failed: {0}")]
    Auth(String),

    #[error("invoke queue is full")]
    QueueFull,

    #[error("invalid endpoint URL scheme: {0}")]
    InvalidScheme(String),

    #[error("invalid outbound header: {0}")]
    InvalidHeader(String),

    #[error("{0}")]
    Other(String),
}

impl InvokeError {
    /// Stable machine-readable error code for Python interop.
    pub fn error_code(&self) -> &'static str {
        match self {
            Self::Timeout(_) => "timeout",
            Self::Connection(_) => "connection",
            Self::AgentHttp(_) => "agent_http",
            Self::OversizedResponse { .. } => "oversized_response",
            Self::CircuitOpen => "circuit_open",
            Self::Auth(_) => "auth",
            Self::QueueFull => "queue_full",
            Self::InvalidScheme(_) => "invalid_scheme",
            Self::InvalidHeader(_) => "invalid_header",
            Self::Other(_) => "other",
        }
    }

    /// HTTP status code to return to the Python caller.
    pub fn http_status(&self) -> StatusCode {
        match self {
            Self::Timeout(_) => StatusCode::GATEWAY_TIMEOUT,
            Self::CircuitOpen | Self::QueueFull => StatusCode::SERVICE_UNAVAILABLE,
            Self::OversizedResponse { .. } => StatusCode::BAD_REQUEST,
            Self::Auth(_) => StatusCode::BAD_REQUEST,
            Self::InvalidScheme(_) | Self::InvalidHeader(_) => StatusCode::BAD_REQUEST,
            _ => StatusCode::BAD_GATEWAY,
        }
    }

    /// Whether this error is transient and the request should be retried.
    pub fn is_retryable(&self) -> bool {
        match self {
            Self::Timeout(_) | Self::Connection(_) => true,
            Self::AgentHttp(code) => (500..600).contains(code),
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timeout_is_retryable() {
        let err = InvokeError::Timeout(Duration::from_secs(30));
        assert!(err.is_retryable());
        assert_eq!(err.error_code(), "timeout");
        assert_eq!(err.http_status(), StatusCode::GATEWAY_TIMEOUT);
    }

    #[test]
    fn agent_5xx_is_retryable() {
        assert!(InvokeError::AgentHttp(502).is_retryable());
        assert!(InvokeError::AgentHttp(503).is_retryable());
    }

    #[test]
    fn agent_4xx_is_not_retryable() {
        assert!(!InvokeError::AgentHttp(400).is_retryable());
        assert!(!InvokeError::AgentHttp(404).is_retryable());
    }

    #[test]
    fn oversized_response_is_not_retryable() {
        let err = InvokeError::OversizedResponse { limit: 10_000_000 };
        assert!(!err.is_retryable());
        assert_eq!(err.http_status(), StatusCode::BAD_REQUEST);
    }

    #[test]
    fn invalid_scheme_is_not_retryable() {
        let err = InvokeError::InvalidScheme("file".to_string());
        assert!(!err.is_retryable());
        assert_eq!(err.error_code(), "invalid_scheme");
    }

    #[test]
    fn error_codes_cover_remaining_variants() {
        assert_eq!(
            InvokeError::Connection("offline".to_string()).error_code(),
            "connection"
        );
        assert_eq!(InvokeError::AgentHttp(500).error_code(), "agent_http");
        assert_eq!(InvokeError::CircuitOpen.error_code(), "circuit_open");
        assert_eq!(InvokeError::Auth("bad".to_string()).error_code(), "auth");
        assert_eq!(InvokeError::QueueFull.error_code(), "queue_full");
        assert_eq!(
            InvokeError::InvalidHeader("bad".to_string()).error_code(),
            "invalid_header"
        );
        assert_eq!(InvokeError::Other("bad".to_string()).error_code(), "other");
    }

    #[test]
    fn http_statuses_cover_remaining_variants() {
        assert_eq!(
            InvokeError::Connection("offline".to_string()).http_status(),
            StatusCode::BAD_GATEWAY
        );
        assert_eq!(
            InvokeError::AgentHttp(503).http_status(),
            StatusCode::BAD_GATEWAY
        );
        assert_eq!(
            InvokeError::CircuitOpen.http_status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            InvokeError::QueueFull.http_status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            InvokeError::Auth("bad".to_string()).http_status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            InvokeError::InvalidHeader("bad".to_string()).http_status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            InvokeError::Other("bad".to_string()).http_status(),
            StatusCode::BAD_GATEWAY
        );
    }
}
