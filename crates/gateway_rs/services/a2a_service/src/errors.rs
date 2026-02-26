use std::time::Duration;

use thiserror::Error;

/// Error type for A2A HTTP invocation errors.
#[derive(Debug, Error)]
pub enum A2AError {
    /// Underlying HTTP client error.
    #[error(transparent)]
    Http(#[from] reqwest::Error),

    /// Request timed out.
    #[error("A2A request timed out after {0:?}")]
    Timeout(Duration),

    /// Authentication or authorization related error.
    #[error("A2A auth error: {0}")]
    Auth(String),

    /// Generic invocation error.
    #[error("A2A invocation error: {0}")]
    Other(String),
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
}
