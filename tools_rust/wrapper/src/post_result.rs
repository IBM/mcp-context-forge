use bytes::Bytes;

#[derive(Debug, Clone)]
#[allow(dead_code)]
/// struct hold post result data
pub struct PostResult {
    /// session id returned by mcp on init
    pub session_id: Option<String>,
    /// output text
    pub out: Vec<Bytes>,
    pub sse: bool,
}
