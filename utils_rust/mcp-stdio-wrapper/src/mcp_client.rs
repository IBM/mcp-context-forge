use std::collections::HashMap;
use tokio::sync::oneshot;
use std::sync::{Arc, Mutex};

pub struct RawMcpClient {
    pub to_server: Sender<String>,
    pub pending: Arc<Mutex<HashMap<String, oneshot::Sender<String>>>>,
}

impl RawMcpClient {
    pub async fn send_and_wait(&self, id: &str, raw_json: String) -> String {
        let (tx, rx) = oneshot::channel();

        // 1. Register the ID we are waiting for
        self.pending.lock().unwrap().insert(id.to_string(), tx);

        // 2. Send the raw string to the server via the Writer
        self.to_server.send_async(raw_json).await.unwrap();

        // 3. Wait for the response handler to wake us up
        rx.await.unwrap()
    }
}