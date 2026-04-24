pub(crate) fn sanitize_response_body_bytes(body: &[u8]) -> Vec<u8> {
    String::from_utf8_lossy(body)
        .chars()
        .filter(|ch| {
            let code = *ch as u32;
            !(matches!(code, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f..=0x9f))
        })
        .collect::<String>()
        .into_bytes()
}
