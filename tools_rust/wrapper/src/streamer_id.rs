use crate::streamer::McpStreamClient;
use std::sync::Arc;

impl McpStreamClient {
    #[allow(dead_code)]
    /// sets received session id
    pub fn set_session_id(&self, id: Option<String>) {
        if self.session_id.load().is_some() || id.is_none() {
            return;
        }
        let new_val = Arc::new(id);
        self.session_id.rcu(|current| {
            if current.is_some() {
                Arc::clone(current)
            } else {
                Arc::clone(&new_val)
            }
        });
    }
    #[allow(dead_code)]
    ///  session id
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
