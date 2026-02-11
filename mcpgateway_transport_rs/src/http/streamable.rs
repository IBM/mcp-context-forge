use std::collections::HashMap;

pub fn extract_server_id(path: &str) -> Option<String> {
    let marker = "/servers/";
    let start = path.find(marker)? + marker.len();
    let rest = &path[start..];
    let end = rest.find("/mcp")?;
    let candidate = &rest[..end];

    if candidate.is_empty() {
        return None;
    }

    Some(candidate.to_string())
}

pub fn is_mcp_path(path: &str) -> bool {
    path.ends_with("/mcp") || path.ends_with("/mcp/")
}

pub fn normalize_headers(headers: Vec<(String, String)>) -> HashMap<String, String> {
    let mut normalized = HashMap::new();
    for (k, v) in headers {
        normalized.insert(k.to_ascii_lowercase(), v);
    }
    normalized
}
