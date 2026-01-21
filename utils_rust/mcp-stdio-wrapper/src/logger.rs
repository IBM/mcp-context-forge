use std::io;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// initializes logger to debug by default
pub fn init_logger() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("debug"));

    tracing_subscriber::registry()
        .with(filter)
        .with(
            // mono out to stderr
            fmt::layer() //
                .with_ansi(false)
                .with_writer(io::stderr),
        )
        .init();

    tracing::debug!("Logger initialized with DEBUG level on stderr");
}
