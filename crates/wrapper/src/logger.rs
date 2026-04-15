use crate::config::DEFAULT_LOG_LEVEL;
use std::fs::File;
use std::io;
use std::path::Path;
use std::sync::{Mutex, Once};
use tracing::level_filters;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::{EnvFilter, fmt, prelude::*};

static INIT: Once = Once::new();
static GUARD: Mutex<Option<WorkerGuard>> = Mutex::new(None);

fn open_log_file(path: &str) -> io::Result<File> {
    let log_path = Path::new(path);
    if let Ok(metadata) = std::fs::symlink_metadata(log_path)
        && metadata.file_type().is_symlink()
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "refusing to log to symlink",
        ));
    }

    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
}

fn build_filter(log_level: Option<&str>) -> EnvFilter {
    let level = log_level.unwrap_or(DEFAULT_LOG_LEVEL);
    let builder = EnvFilter::builder().with_default_directive(
        level
            .parse()
            .unwrap_or(level_filters::LevelFilter::OFF.into()),
    );

    if log_level.is_some() {
        builder.parse_lossy("")
    } else {
        builder.from_env_lossy()
    }
}

fn init_logger_once(log_level: Option<&str>, log_file: Option<&str>) {
    let level = log_level.unwrap_or(DEFAULT_LOG_LEVEL);
    if level == "off" {
        return;
    }

    if let Some(path) = log_file {
        match open_log_file(path) {
            Ok(file) => {
                let (non_blocking, guard) = tracing_appender::non_blocking(file);
                let _ = tracing_subscriber::registry()
                    .with(build_filter(log_level))
                    .with(fmt::layer().with_ansi(false).with_writer(non_blocking))
                    .try_init();
                if let Ok(mut guard_lock) = GUARD.lock() {
                    *guard_lock = Some(guard);
                }
                return;
            }
            Err(e) => {
                eprintln!(
                    "WARN: Failed to open log file '{path}', falling back to stderr. Error: {e}"
                );
            }
        }
    }

    let (non_blocking, guard) = tracing_appender::non_blocking(std::io::stderr());
    let _ = tracing_subscriber::registry()
        .with(build_filter(log_level))
        .with(fmt::layer().with_ansi(false).with_writer(non_blocking))
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

#[cfg(test)]
mod tests {
    use super::{build_filter, open_log_file};
    use std::io::ErrorKind;
    use std::io::Write;
    use tracing::level_filters::LevelFilter;

    #[test]
    fn build_filter_uses_explicit_level_without_env() {
        let filter = build_filter(Some("info"));

        assert_eq!(filter.max_level_hint(), Some(LevelFilter::INFO));
    }

    #[test]
    fn build_filter_honors_explicit_off_level() {
        let filter = build_filter(Some("off"));

        assert_eq!(filter.max_level_hint(), Some(LevelFilter::OFF));
    }

    #[test]
    fn build_filter_reads_env_when_level_is_not_explicit() {
        let original = std::env::var("RUST_LOG").ok();
        // SAFETY: this test restores the process-wide env var before returning.
        unsafe {
            std::env::set_var("RUST_LOG", "debug");
        }

        let filter = build_filter(None);

        if let Some(value) = original {
            // SAFETY: restore original process-wide env var before the test exits.
            unsafe {
                std::env::set_var("RUST_LOG", value);
            }
        } else {
            // SAFETY: remove the temporary test env var before the test exits.
            unsafe {
                std::env::remove_var("RUST_LOG");
            }
        }

        assert_eq!(filter.max_level_hint(), Some(LevelFilter::DEBUG));
    }

    #[test]
    fn open_log_file_creates_missing_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let path = temp_dir.path().join("wrapper.log");

        let _file = open_log_file(path.to_str().unwrap()).unwrap();

        assert!(path.exists());
    }

    #[test]
    fn open_log_file_appends_existing_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let path = temp_dir.path().join("wrapper.log");
        std::fs::write(&path, "first\n").unwrap();
        let mut file = open_log_file(path.to_str().unwrap()).unwrap();
        file.write_all(b"second\n").unwrap();
        drop(file);

        let contents = std::fs::read_to_string(&path).unwrap();
        assert!(contents.contains("first"));
        assert!(contents.contains("second"));
    }

    #[cfg(unix)]
    #[test]
    fn open_log_file_rejects_symlink() {
        let temp_dir = tempfile::tempdir().unwrap();
        let target = temp_dir.path().join("target.log");
        let link = temp_dir.path().join("link.log");
        std::fs::write(&target, "x").unwrap();
        std::os::unix::fs::symlink(&target, &link).unwrap();

        let err = open_log_file(link.to_str().unwrap()).unwrap_err();
        assert_eq!(err.kind(), ErrorKind::InvalidInput);
    }
}
