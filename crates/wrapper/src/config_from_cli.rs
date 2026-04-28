use crate::config::Config;
use clap::Parser;
use std::ffi::OsString;

/// implements config init from cli arguments
impl Config {
    /// loads config from cli arguments
    #[must_use]
    pub fn from_cli<I, T>(args: I) -> Self
    where
        I: IntoIterator<Item = T>,
        T: Into<OsString> + Clone,
    {
        Config::parse_from(args)
    }
}
