use bytes::Bytes;

#[derive(Debug, Clone)]
#[allow(dead_code)]
/// struct hold post result data
pub struct PostResult {
    /// output text
    pub out: Vec<Bytes>,
    /// http event flag
    pub sse: bool,
}
