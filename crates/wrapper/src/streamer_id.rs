use crate::streamer::McpStreamClient;
use std::sync::Arc;

impl McpStreamClient {
    /// sets received session id
    pub fn set_session_id(&self, new_id: &str) {
        let mut current_guard = self.session_id.load();
        if current_guard.as_deref() == Some(new_id) {
            return; // no update
        }
        let new_arc = Arc::new(Some(new_id.to_string()));
        loop {
            let prev_guard = self // safe update
                .session_id
                .compare_and_swap(&*current_guard, Arc::clone(&new_arc));

            if Arc::ptr_eq(&*prev_guard, &*current_guard) {
                return; // Success
            }
            current_guard = prev_guard;
            if current_guard.as_deref() == Some(new_id) {
                return; // another thread set it to the desired value
            }
        }
    }

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
