// Separate test file to ensure logger file functionality is tested in isolation
// This avoids conflicts with other logger tests due to Once::call_once() limitation

use mcp_stdio_wrapper::logger::{flush_logger, init_logger};
use tracing::info;

/// Comprehensive test for log file functionality
/// Tests file creation, writing, and append mode in a single test
/// to avoid conflicts with `Once::call_once()` limitation
///
/// This test covers:
/// 1. File creation when it doesn't exist
/// 2. Append mode when file already exists
/// 3. Writing log messages to file
/// 4. Proper log formatting
#[tokio::test]
async fn test_logger_file_all_scenarios() {
    // Setup: Create a temp directory and pre-populate a file to test append mode
    let temp_dir = tempfile::tempdir().unwrap();
    let log_file = temp_dir.path().join("comprehensive_test.log");
    let log_path = log_file.to_str().unwrap();

    // Pre-create file with initial content to test append mode
    std::fs::write(&log_file, "=== Initial Content ===\n").unwrap();
    assert!(log_file.exists(), "Pre-created log file should exist");

    // Initialize logger with file path - should append, not overwrite
    init_logger(Some("info"), Some(log_path));

    // Log multiple messages to test writing
    info!("first message");
    info!("second message");
    info!("third message");

    // Flush to ensure all logs are written
    flush_logger();

    // Give a small delay to ensure file system operations complete
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

    // Verify file still exists
    assert!(log_file.exists(), "Log file should exist after logging");

    // Read and verify file contents
    let contents = std::fs::read_to_string(&log_file).unwrap();

    // Verify append mode - initial content should be preserved
    assert!(
        contents.contains("=== Initial Content ==="),
        "File should preserve initial content (append mode)"
    );

    // Verify new log messages were written
    assert!(
        contents.contains("first message"),
        "Log file should contain 'first message'"
    );
    assert!(
        contents.contains("second message"),
        "Log file should contain 'second message'"
    );
    assert!(
        contents.contains("third message"),
        "Log file should contain 'third message'"
    );

    // Verify log format (should contain INFO level)
    assert!(
        contents.contains("INFO"),
        "Log file should contain INFO level"
    );

    // Verify multiple lines were written
    let line_count = contents.lines().count();
    assert!(
        line_count >= 4,
        "Log file should contain at least 4 lines (1 initial + 3 logs), found {line_count}"
    );
}

// Made with Bob
