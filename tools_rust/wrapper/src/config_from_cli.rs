use crate::config::{Config, normalize_url};
use clap::Parser;
use std::ffi::OsString;

/// implements config init from cli arguments
impl Config {
    /// loads config from cli arguments, normalizing the server URL
    #[must_use]
    pub fn from_cli<I, T>(args: I) -> Self
    where
        I: IntoIterator<Item = T>,
        T: Into<OsString> + Clone,
    {
        let mut config = Config::parse_from(args);
        config.mcp_server_url = normalize_url(&config.mcp_server_url);
        config
    }
}
