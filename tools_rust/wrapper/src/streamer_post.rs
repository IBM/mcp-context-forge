use crate::post_result::PostResult;
use crate::streamer::McpStreamClient;
use crate::streamer_lines::extract_lines;
use bytes::{Bytes, BytesMut};
use futures::StreamExt;
use reqwest::Client;
use reqwest::header::CONTENT_TYPE;
use tracing::{debug, error};

impl McpStreamClient {
    /// Performs a streaming POST request and processes the response into lines of bytes.
    /// # Errors
    /// This function will return an error if the request or stream processing fails.
    pub async fn stream_post(&self, client: &Client, payload: Bytes) -> Result<PostResult, String> {
        let response = self.prepare_and_send_request(client, payload).await?;
        let status = response.status();

        if !status.is_success() {
            let err_text = response
                .text()
                .await
                .unwrap_or_else(|_| "Could not read error body".to_string());

            error!("Server returned error {}: {}", status, err_text);
            return Err(format!("Server error {status}: {err_text}"));
        }

        let sse = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .is_some_and(|s| s.contains("text/event-stream"));

        self.process_session_id(&response);

        let mut out = Vec::new();
        let mut buffer = BytesMut::new();
        let mut stream = response.bytes_stream();

        while let Some(item) = stream.next().await {
            match item {
                Ok(chunk) => {
                    buffer.extend_from_slice(&chunk);
                    extract_lines(&mut buffer, &mut out);
                }
                Err(e) => return Err(format!("Stream interrupted: {e}")),
            }
        }

        if !buffer.is_empty() {
            out.push(buffer.freeze());
        }
        debug!("Received lines: {out:?}");

        Ok(PostResult { out, sse })
    }
}
