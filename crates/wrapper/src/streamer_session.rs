use crate::streamer::{McpStreamClient, SID};
use reqwest::Response;
use tracing::error;

impl McpStreamClient {
    /// saves session id for future use
    pub fn process_session_id(&self, response: &Response) {
        if let Some(val) = response.headers().get(SID) {
            match val.to_str() {
                Ok(s) => self.set_session_id(s),
                Err(e) => error!("Invalid header: {e}"),
            }
        }
    }
}
