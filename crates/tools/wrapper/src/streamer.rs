use crate::config::Config;
use arc_swap::ArcSwap;
use reqwest::header::HeaderMap;

pub const SID: &str = "mcp-session-id";

#[derive(Debug)]
pub struct McpStreamClient {
    //pub(crate) client: Client,
    pub(crate) session_id: ArcSwap<Option<String>>,
    pub(crate) config: Config,
    pub(crate) static_headers: HeaderMap,
}
