//! Error type for A2A HTTP invocation.
//!
//! Used by the invoker and exposed to Python when a request fails (e.g. timeout, connection error, circuit open).

use std::time::Duration;

use thiserror::Error;

/// Errors that can occur during an A2A HTTP invocation.
#[derive(Debug, Error)]
pub enum A2AError {
    /// Underlying HTTP client error.
    #[error(transparent)]
    Http(#[from] reqwest::Error),

    /// Request timed out.
    #[error("A2A request timed out after {0:?}")]
    Timeout(Duration),

    /// Per-endpoint circuit breaker is open; request rejected.
    #[error("Circuit breaker open for endpoint")]
    CircuitOpen,

    /// Response body exceeded maximum allowed size.
    #[error("Response body exceeds maximum allowed size")]
    OversizedResponse,

    /// Authentication or authorization related error.
    #[error("A2A auth error: {0}")]
    Auth(String),

    /// Generic invocation error.
    #[error("A2A invocation error: {0}")]
    Other(String),
}


/// Returns true if the HTTP status code indicates success (2xx).
#[inline]
pub fn is_success_http_status(code: u16) -> bool {
    (200..300).contains(&code)
}

impl A2AError {
    /// Stable error code for Python/API to map to HTTP status and retry behavior.
    pub fn error_code(&self) -> &'static str {
        match self {
            A2AError::Timeout(_) => "timeout",
            A2AError::CircuitOpen => "circuit_open",
            A2AError::OversizedResponse => "oversized_response",
            A2AError::Http(e) if e.is_timeout() => "timeout",
            A2AError::Http(_) => "http",
            A2AError::Auth(_) => "auth",
            A2AError::Other(_) => "other",
        }
    }

    /// HTTP status code to use when this error is returned to the client.
    pub fn http_status(&self) -> u16 {
        match self {
            A2AError::Timeout(_) => 504,
            A2AError::Http(e) if e.is_timeout() => 504,
            A2AError::CircuitOpen => 503,
            A2AError::OversizedResponse => 413,
            A2AError::Http(_) | A2AError::Auth(_) | A2AError::Other(_) => 502,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_a2a_error_timeout_display() {
        let error = A2AError::Timeout(Duration::from_secs(5));
        assert!(error.to_string().contains("timed out"));
        assert!(error.to_string().contains("5s"));
    }

    #[test]
    fn test_a2a_error_auth_display() {
        let error = A2AError::Auth("invalid token".to_string());
        assert_eq!(error.to_string(), "A2A auth error: invalid token");
    }

    #[test]
    fn test_a2a_error_other_display() {
        let error = A2AError::Other("something went wrong".to_string());
        assert_eq!(error.to_string(), "A2A invocation error: something went wrong");
    }

    #[test]
    fn test_a2a_error_codes_and_status() {
        assert_eq!(A2AError::Timeout(Duration::from_secs(5)).error_code(), "timeout");
        assert_eq!(A2AError::Timeout(Duration::from_secs(5)).http_status(), 504);
        assert_eq!(A2AError::CircuitOpen.error_code(), "circuit_open");
        assert_eq!(A2AError::CircuitOpen.http_status(), 503);
        assert_eq!(A2AError::OversizedResponse.error_code(), "oversized_response");
        assert_eq!(A2AError::OversizedResponse.http_status(), 413);
    }

    #[test]
    fn test_a2a_error_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<A2AError>();
    }
}
