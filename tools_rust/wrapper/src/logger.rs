use crate::config::DEFAULT_LOG_LEVEL;
use std::sync::{Mutex, Once};
use tracing::level_filters;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::{EnvFilter, fmt, prelude::*};

static INIT: Once = Once::new();
static GUARD: Mutex<Option<WorkerGuard>> = Mutex::new(None);
fn init_logger_once(log_level: Option<&str>, log_file: Option<&str>) {
    let def_level = DEFAULT_LOG_LEVEL;

    let level = log_level.unwrap_or(def_level);
    if level == "off" {
        return;
    }

    let (non_blocking, guard) = if let Some(path) = log_file {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
        {
            Ok(file) => tracing_appender::non_blocking(file),
            Err(e) => {
                eprintln!(
                    "WARN: Failed to open log file '{path}', falling back to stderr. Error: {e}"
                );
                tracing_appender::non_blocking(std::io::stderr())
            }
        }
    } else {
        tracing_appender::non_blocking(std::io::stderr())
    };

    let filter = EnvFilter::builder() //
        .with_default_directive(
            level
                .parse()
                .unwrap_or(level_filters::LevelFilter::OFF.into()),
        )
        .from_env_lossy();

    let layer = fmt::layer() //
        .with_ansi(false)
        .with_writer(non_blocking);

    let _ = tracing_subscriber::registry()
        .with(filter)
        .with(layer)
        .try_init();

    if let Ok(mut guard_lock) = GUARD.lock() {
        *guard_lock = Some(guard);
    }
}

/// initializes logger
pub fn init_logger(log_level: Option<&str>, log_file: Option<&str>) {
    INIT.call_once(|| init_logger_once(log_level, log_file));
}

/// Flushes and shuts down the global logger.
/// Call this at the end of tests to ensure logs are written before file deletion.
pub fn flush_logger() {
    if let Ok(mut guard_lock) = GUARD.lock() {
        *guard_lock = None; // Dropping the guard forces a flush
    }
}
