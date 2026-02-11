use crate::streamer::McpStreamClient;
use std::sync::Arc;

impl McpStreamClient {
    /// Sets received session id
    pub fn set_session_id(&self, new_id: &str) {
        let current = self.session_id.load();
        if current.as_deref() == Some(new_id) {
            return;
        }
        self.session_id.store(Arc::new(Some(new_id.to_string())));
    }

    /// Returns the current session id
    #[must_use]
    pub fn get_session_id(&self) -> Option<String> {
        let guard = self.session_id.load();
        (**guard).clone()
    }

    /// Returns `true` if the MCP session has been initialized
    pub fn is_ready(&self) -> bool {
        self.session_id.load().is_some()
    }
}
