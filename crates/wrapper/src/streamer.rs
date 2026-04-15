use crate::config::Config;
use arc_swap::ArcSwap;
use reqwest::header::HeaderMap;
use std::fmt;

pub const SID: &str = "mcp-session-id";

pub struct McpStreamClient {
    //pub(crate) client: Client,
    pub(crate) session_id: ArcSwap<Option<String>>,
    pub(crate) config: Config,
    pub(crate) static_headers: HeaderMap,
}

impl fmt::Debug for McpStreamClient {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("McpStreamClient")
            .field("session_id_present", &self.is_ready())
            .field("config", &self.config)
            .field(
                "authorization_header_present",
                &self
                    .static_headers
                    .contains_key(reqwest::header::AUTHORIZATION),
            )
            .finish()
    }
}
