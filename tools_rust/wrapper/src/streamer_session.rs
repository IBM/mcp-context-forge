use crate::streamer::{McpStreamClient, SID};
use reqwest::Response;
use tracing::{debug, error};

impl McpStreamClient {
    /// saves session id for future use
    pub fn process_session_id(&self, response: &Response) -> Option<String> {
        if let Some(val) = response.headers().get(SID) {
            if let Ok(s) = val.to_str() {
                self.set_session_id(Some(s.to_string()));
                Some(s.to_string())
            } else {
                error!("Header contains invalid characters");
                None
            }
        } else {
            if !self.is_ready() {
                debug!("Session id not found");
            }
            None
        }
    }
}
