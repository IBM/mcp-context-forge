use std::time::Duration;

use thiserror::Error;

/// Base error type for A2A agent-related errors.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum A2AAgentError {
    /// Raised when a requested A2A agent is not found.
    #[error("A2A agent not found: {0}")]
    NotFound(String),

    /// Raised when an A2A agent name conflicts with an existing one.
    #[error(
        "A2A agent name conflict: {name} (active: {is_active}, agent_id: {agent_id:?}, visibility: {visibility})"
    )]
    NameConflict {
        name: String,
        is_active: bool,
        agent_id: Option<String>,
        visibility: String,
    },

    /// Generic A2A agent operation error.
    #[error("A2A agent error: {0}")]
    Operation(String),

    /// Permission denied error.
    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    /// Invalid value error.
    #[error("Invalid value: {0}")]
    ValueError(String),
}

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
    fn test_not_found_error_display() {
        let error = A2AAgentError::NotFound("agent-123".to_string());
        assert_eq!(error.to_string(), "A2A agent not found: agent-123");
    }

    #[test]
    fn test_name_conflict_error_display() {
        let error = A2AAgentError::NameConflict {
            name: "test-agent".to_string(),
            is_active: true,
            agent_id: Some("agent-456".to_string()),
            visibility: "public".to_string(),
        };
        assert_eq!(
            error.to_string(),
            "A2A agent name conflict: test-agent (active: true, agent_id: Some(\"agent-456\"), visibility: public)"
        );
    }

    #[test]
    fn test_operation_error_display() {
        let error = A2AAgentError::Operation("Failed to invoke agent".to_string());
        assert_eq!(error.to_string(), "A2A agent error: Failed to invoke agent");
    }

    #[test]
    fn test_permission_denied_error_display() {
        let error =
            A2AAgentError::PermissionDenied("Only the owner can delete this agent".to_string());
        assert_eq!(
            error.to_string(),
            "Permission denied: Only the owner can delete this agent"
        );
    }

    #[test]
    fn test_value_error_display() {
        let error = A2AAgentError::ValueError("Invalid passthrough_headers format".to_string());
        assert_eq!(
            error.to_string(),
            "Invalid value: Invalid passthrough_headers format"
        );
    }

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
