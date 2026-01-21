use crate::post_result::PostResult;
use crate::streamer::{McpStreamClient, SID};
use futures::StreamExt;
use tracing::error;

impl McpStreamClient {
    #[allow(dead_code)]
    /// Opens a stream and pumps raw chunks into the provided flume channel
    /// # Errors
    ///
    /// This function will return an error if the `reqwest` fails
    pub async fn stream_post(&self, payload: String) -> Result<PostResult, String> {
        let mut result = String::new();

        let mut request = self
            .client
            .post(&self.url)
            .body(payload);

        let sid = self.get_session_id().await;
        if let Some(sid) = sid {
            request = request.header(SID, sid);
        }

        let response = request
            .send()
            .await
            .map_err(|e| format!("Request failed: {e}"))?;

        if !response.status().is_success() {
            return Err(format!("Server error: {}", response.status()));
        }

        let id = if let Some(val) = response.headers().get(SID) {
            if let Ok(s) = val.to_str() {
                self.set_session_id(Some(s.to_string())).await;
                Some(s.to_string())
            } else {
                error!("Header contains invalid characters");
                None
            }
        } else {
            error!("Session id not found");
            None
        };

        let mut stream = response.bytes_stream();

        while let Some(item) = stream.next().await {
            match item {
                Ok(bytes) => {
                    let chunk = String::from_utf8_lossy(&bytes);
                    result.push_str(&chunk);
                }
                Err(e) => return Err(format!("Stream interrupted: {e}")),
            }
        }

        Ok(PostResult {
            out: result,
            session_id: id,
        })
    }
}
