use contextforge_stdio_wrapper::config::{Config, normalize_url};

#[test]
pub fn test_config() {
    let args = vec!["wrapper", "--url", "http://localhost:4444/servers/uuid"]
        .into_iter()
        .map(std::string::ToString::to_string);
    let config = Config::from_cli(args);
    assert!(
        config.mcp_server_url.ends_with("/mcp/"),
        "URL should be normalized: {}",
        config.mcp_server_url
    );
}

#[test]
pub fn test_normalize_url() {
    assert_eq!(
        normalize_url("http://localhost:4444/servers/uuid"),
        "http://localhost:4444/servers/uuid/mcp/"
    );
    assert_eq!(
        normalize_url("http://localhost:4444/servers/uuid/sse"),
        "http://localhost:4444/servers/uuid/mcp/"
    );
    assert_eq!(
        normalize_url("http://localhost:4444/servers/uuid/mcp"),
        "http://localhost:4444/servers/uuid/mcp/"
    );
    assert_eq!(
        normalize_url("http://localhost:4444/servers/uuid/mcp/"),
        "http://localhost:4444/servers/uuid/mcp/"
    );
}
