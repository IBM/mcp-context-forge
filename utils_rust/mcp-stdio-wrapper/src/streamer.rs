use reqwest::Client;
use tokio::sync::RwLock;

pub const SID: &'static str = "mcp-session-id";

#[derive(Debug)]
pub struct McpStreamClient {
    pub(crate) client: Client,
    pub(crate) url: String,
    pub(crate) session_id: RwLock<Option<String>>,
}
