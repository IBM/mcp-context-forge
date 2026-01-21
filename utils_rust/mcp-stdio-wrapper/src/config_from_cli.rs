use crate::config::Config;
use clap::Parser;

/// implements config init from cli arguments
impl Config {
    /// loads config from cli arguments
    pub fn from_cli() -> Self {
        Config::parse()
    }
}
