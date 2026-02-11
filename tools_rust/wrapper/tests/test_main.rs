use contextforge_stdio_wrapper::main_init::init_main;

#[test]
fn test_init_main() {
    let fake_args = ["wrapper", "--url", "http://localhost:4444/servers/uuid/mcp/"];
    let config = init_main(fake_args.iter());
    assert_eq!(config.mcp_server_url, "http://localhost:4444/servers/uuid/mcp/");
}
