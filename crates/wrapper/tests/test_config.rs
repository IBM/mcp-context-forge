use mcp_stdio_wrapper::config::Config;
use reqwest::Url;
/// # Panics
/// * test failures
#[test]
pub fn test_config() {
    let args = vec![
        //
        "wrapper", "--url", "url",
    ]
    .into_iter()
    .map(std::string::ToString::to_string);
    let config = Config::from_cli(args);
    assert!(format!("{config:?}").contains("mcp_server_url"));
}

#[test]
pub fn test_config_debug_redacts_auth() {
    let config = Config::from_cli(["wrapper", "--url", "url", "--auth", "super-secret-token"]);

    let rendered = format!("{config:?}");
    assert!(!rendered.contains("super-secret-token"));
    assert!(rendered.contains("<redacted>"));
}

#[test]
pub fn test_config_debug_redacts_url_credentials() {
    let mut url = Url::parse("https://example.com/mcp").expect("valid URL");
    url.set_username("user").expect("set username");
    url.set_password(Some("secret")).expect("set password");
    let config = Config::from_cli(["wrapper", "--url", url.as_str()]);

    let rendered = format!("{config:?}");
    assert!(!rendered.contains("secret"));
    assert!(!rendered.contains("user:"));
    assert!(rendered.contains("redacted@example.com"));
}
