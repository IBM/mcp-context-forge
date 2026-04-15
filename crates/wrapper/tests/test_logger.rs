use mcp_stdio_wrapper::logger::{flush_logger, init_logger};
use tracing::info;

#[test]
fn logger_init_is_idempotent() {
    init_logger(Some("info"), None);
    info!("logger smoke test");
    flush_logger();

    init_logger(Some("off"), None);
    init_logger(Some("invalid_level_xyz"), None);
    init_logger(None, None);
    flush_logger();
}
