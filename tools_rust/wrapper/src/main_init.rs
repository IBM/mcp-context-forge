use crate::config::Config;
use crate::logger::init_logger;
use tracing::debug;

pub fn init_main<I, T>(args: I) -> Config
where
    I: IntoIterator<Item = T>,
    T: Into<std::ffi::OsString> + Clone,
{
    let config = Config::from_cli(args);
    init_logger(
        Some(&config.mcp_wrapper_log_level),
        config.mcp_wrapper_log_file.as_deref(),
    );
    debug!("{config:?}");
    debug!("Start");
    config
}
