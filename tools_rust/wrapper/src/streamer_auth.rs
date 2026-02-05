use crate::streamer::McpStreamClient;

impl McpStreamClient {
    pub fn is_auth(&self) -> bool {
        self.config.mcp_auth.is_some()
    }
}
