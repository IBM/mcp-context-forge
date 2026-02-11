use bytes::Bytes;

#[derive(Debug, Clone)]
/// Holds the result of a streaming POST request
pub struct PostResult {
    /// output text
    pub out: Vec<Bytes>,
    /// http event flag
    pub sse: bool,
}
