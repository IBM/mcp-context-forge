use bytes::{Bytes, BytesMut};

const LF: u8 = b'\n';
const CRLF: &[u8] = b"\r\n";
const CRLF_LEN: usize = 2;
const LF_LEN: usize = 1;

/// Extracts complete lines from the buffer and pushes them into the lines vector.
pub fn extract_lines(buffer: &mut BytesMut, lines: &mut Vec<Bytes>) {
    while let Some(pos) = buffer.iter().position(|&b| b == LF) {
        // split_to is O(1) and zero-copy, it moves the data out of the buffer
        let mut line = buffer.split_to(pos + 1);

        // Remove line terminators
        if line.ends_with(CRLF) {
            line.truncate(line.len() - CRLF_LEN);
        } else if line.last() == Some(&LF) {
            line.truncate(line.len() - LF_LEN);
        }

        if !line.is_empty() {
            lines.push(line.freeze());
        }
    }
}
