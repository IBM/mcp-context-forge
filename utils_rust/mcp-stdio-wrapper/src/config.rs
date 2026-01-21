use clap::Parser;
use serde::Deserialize;

#[derive(Deserialize, Debug, Parser)]
pub struct Config {
    #[serde(default = "crate::config_defaults::default_concurrency")]
    #[arg(long, default_value_t = crate::config_defaults::default_concurrency())]
    pub concurrency: usize,

    #[serde(default = "crate::config_defaults::default_mcp_server_url")]
    #[arg(long, default_value_t = crate::config_defaults::default_mcp_server_url())]
    pub mcp_server_url: String,

    #[serde(default = "crate::config_defaults::default_mcp_wrapper_log_level")]
    #[arg(long, default_value_t = crate::config_defaults::default_mcp_wrapper_log_level())]
    pub mcp_wrapper_log_level: String,
}
