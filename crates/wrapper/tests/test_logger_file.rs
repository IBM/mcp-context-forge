// Separate test file to ensure logger file functionality is tested in isolation
// This avoids conflicts with other logger tests due to Once::call_once() limitation

use mcp_stdio_wrapper::logger::{flush_logger, init_logger};
use tracing::info;

/// Comprehensive test for log file functionality
/// Tests fresh file creation and writing in a single test
/// to avoid conflicts with `Once::call_once()` limitation
///
/// This test covers:
/// 1. File creation when it doesn't exist
/// 2. Writing log messages to file
/// 3. Proper log formatting
#[tokio::test]
async fn test_logger_file_all_scenarios() {
    let temp_dir = tempfile::tempdir().unwrap();
    let log_file = temp_dir.path().join("comprehensive_test.log");
    let log_path = log_file.to_str().unwrap();

    assert!(!log_file.exists(), "log file should start absent");

    init_logger(Some("info"), Some(log_path));

    // Log multiple messages to test writing
    info!("first message");
    info!("second message");
    info!("third message");

    // Flush to ensure all logs are written
    flush_logger();

    let contents = tokio::time::timeout(tokio::time::Duration::from_secs(2), async {
        loop {
            let contents = std::fs::read_to_string(&log_file).unwrap();
            if contents.contains("first message")
                && contents.contains("second message")
                && contents.contains("third message")
            {
                break contents;
            }
            tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("log file should contain all messages after flush");

    assert!(log_file.exists(), "logger should create the log file");

    assert!(
        contents.contains("INFO"),
        "Log file should contain INFO level"
    );

    let line_count = contents.lines().count();
    assert!(
        line_count >= 3,
        "Log file should contain at least 3 log lines, found {line_count}"
    );
}

// Made with Bob
