use mcp_stdio_wrapper::logger::{flush_logger, init_logger};
use tracing::info;
/// # Panics
/// * test failures

#[tokio::test]
pub async fn test_logger_init_off() {
    init_logger(Some("off"), None);
}
/// # Panics
/// * test failures

#[tokio::test]
pub async fn test_logger_init_info() {
    init_logger(Some("info"), None);
}

#[tokio::test]
async fn test_logger_init_file_invalid_path() {
    // Test with an invalid/inaccessible path to trigger the error handling
    let invalid_path = "/invalid/nonexistent/path/test.log";

    init_logger(Some("info"), Some(invalid_path));
    info!("test message with fallback to stderr");
    flush_logger();
}

#[tokio::test]
async fn test_logger_init_invalid_level() {
    // Test with an invalid log level to trigger the fallback to OFF
    let temp_dir = tempfile::tempdir().unwrap();
    let log_file = temp_dir.path().join("invalid_level.log");
    let log_path = log_file.to_str().unwrap();

    init_logger(Some("invalid_level_xyz"), Some(log_path));
    info!("this should not be logged due to invalid level");
    flush_logger();
}

#[tokio::test]
async fn test_logger_init_default_level() {
    // Test with None log_level to use default
    let temp_dir = tempfile::tempdir().unwrap();
    let log_file = temp_dir.path().join("default_level.log");
    let log_path = log_file.to_str().unwrap();

    init_logger(None, Some(log_path));
    info!("test with default log level");
    flush_logger();
}

// Made with Bob
