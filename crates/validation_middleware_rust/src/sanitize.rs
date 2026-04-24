pub(crate) fn sanitize_response_body_bytes(body: &[u8]) -> Vec<u8> {
    let mut has_control = false;
    let mut has_non_ascii = false;

    for byte in body {
        if matches!(byte, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f..=0x9f) {
            has_control = true;
            break;
        }
        if !byte.is_ascii() {
            has_non_ascii = true;
        }
    }

    if !has_control && (!has_non_ascii || std::str::from_utf8(body).is_ok()) {
        return body.to_vec();
    }

    String::from_utf8_lossy(body)
        .chars()
        .filter(|ch| {
            let code = *ch as u32;
            !(matches!(code, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f..=0x9f))
        })
        .collect::<String>()
        .into_bytes()
}
