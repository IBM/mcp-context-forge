use crate::streamer::McpStreamClient;

impl McpStreamClient {
    #[allow(dead_code)]
    /// sets received session id
    pub async fn set_session_id(&self, id: Option<String>) {
        {
            let read_guard = self.session_id.read().await;
            if read_guard.is_some() || id.is_none() {
                return;
            }
        }

        let mut write_guard = self.session_id.write().await;

        if write_guard.is_none() {
            *write_guard = id;
        }
    }
    #[allow(dead_code)]
    ///  session id
    #[must_use]
    pub async fn get_session_id(&self) -> Option<String> {
        let read_guard = self.session_id.read().await;
        read_guard.clone()
    }
}
