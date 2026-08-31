use crate::streamer::McpStreamClient;

impl McpStreamClient {
    pub fn is_auth(&self) -> bool {
        self.config.authorization_header.is_some()
    }
}
