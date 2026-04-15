use crate::json_rpc_id_fast::parse_id_fast;
use bytes::Bytes;
use flume::Sender;
use jsonrpc_core::{Error, ErrorCode, Failure, Version, serde_json};
use serde_json::json;
use std::path::Path;
use tracing::error;

/// creates error message
pub async fn mcp_error(
    //
    worker_id: &usize,
    json_str: &[u8],
    error_msg: &str,
    tx: &Sender<Bytes>,
) {
    let id = parse_id_fast(json_str);
    tracing::debug!("Json rpc id:{id:?}");
    let error_obj = Error {
        code: ErrorCode::InternalError,
        message: error_msg.to_string(),
        data: None,
    };

    let response = Failure {
        jsonrpc: Some(Version::V2),
        error: error_obj,
        id,
    };

    let json_msg = match serde_json::to_string(&response) {
        Ok(msg) => msg,
        Err(e) => rpc_error(&response, &e),
    };

    if let Err(e) = tx.send_async(Bytes::from(json_msg)).await {
        error!("Worker {worker_id}: failed to send JSON-RPC response: {e}");
    }
}
/// creates error message
#[must_use]
pub fn rpc_error(failure: &Failure, e: &serde_json::Error) -> String {
    json!({
        "jsonrpc": "2.0",
        "error": {"code": ErrorCode::InternalError,"message": e.to_string()},
        "id": failure.id,
    })
    .to_string()
}
/// creates error message
#[must_use]
pub fn invalid_error(path: &Path, e: &reqwest::Error) -> String {
    format!("Invalid PEM in cert file {}: {}", path.display(), e)
}
/// creates error message
#[must_use]
pub fn read_error(path: &Path, e: &std::io::Error) -> String {
    format!("Failed to read cert file {}: {}", path.display(), e)
}
/// creates error message
#[must_use]
pub fn build_error(e: &reqwest::Error) -> String {
    format!("Http client build error {e}")
}
