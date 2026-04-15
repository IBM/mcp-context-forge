use bytes::{Bytes, BytesMut};
use mcp_stdio_wrapper::streamer_lines::extract_lines;

/// tests buffer split cr/lf
/// # Panics
/// * test failure
#[test]
pub fn test_process_lines() {
    let mut buffer = BytesMut::from("asdf\r\njkl\n");
    let mut lines: Vec<Bytes> = Vec::new();

    extract_lines(&mut buffer, &mut lines);

    println!("lines: {lines:?}");
    let asdf = Bytes::from("asdf");
    let jkl = Bytes::from("jkl");
    assert_eq!(vec![asdf, jkl], lines);
}
