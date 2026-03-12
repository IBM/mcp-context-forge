use mcp_stdio_wrapper::config::Config;
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
    let _config = Config::from_cli(args);
}
