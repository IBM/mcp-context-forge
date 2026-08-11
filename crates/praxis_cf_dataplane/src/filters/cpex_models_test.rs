use super::{PolicyMapping, PolicyProfile, ServerId, parse_server_path};

#[test]
fn accepts_exact_server_path_only() {
    assert_eq!(
        parse_server_path("/servers/server-a/mcp", None),
        Ok(ServerId::new("server-a").expect("valid id"))
    );
    for path in [
        "/servers//mcp",
        "/server/server-a/mcp",
        "/servers/server-a/mcp/extra",
        "/servers/../mcp",
        "/servers/a%2Fb/mcp",
    ] {
        assert!(parse_server_path(path, None).is_err(), "accepted {path}");
    }
    assert!(parse_server_path("/servers/server-a/mcp", Some("x=1")).is_err());
}

#[test]
fn canonical_policy_mapping_rejects_wrong_or_absolute_paths() {
    assert!(PolicyMapping::new("server-a", "cpex/team--server-a.yaml").is_ok());
    for path in [
        "/cpex/team--server-a.yaml",
        "cpex/../team--server-a.yaml",
        "policies/team--server-a.yaml",
        "cpex/team--server-b.yaml",
    ] {
        assert!(
            PolicyMapping::new("server-a", path).is_err(),
            "accepted {path}"
        );
    }
}

#[test]
fn profile_matches_exact_tool_resource_uri_and_prompt_only() {
    let yaml = r#"
plugin_settings:
  routing_enabled: true
  fail_on_plugin_error: true
routes:
  - prompt: brief
  - resource: https://docs.example.test/guide
  - tool: search
  - tool: "*"
  - resource: "*"
  - prompt: "*"
"#;
    let config = cpex::cpex_core::config::parse_config(yaml).expect("valid CPEX");
    let profile = PolicyProfile::try_from(config).expect("valid profile");

    for (method, exact, neighbor) in [
        ("tools/call", "search", "search-next"),
        (
            "resources/read",
            "https://docs.example.test/guide",
            "https://docs.example.test/guide-next",
        ),
        ("prompts/get", "brief", "brief-next"),
    ] {
        assert!(profile.allows(method, exact));
        assert!(!profile.allows(method, neighbor));
    }
}

#[test]
fn profile_rejects_missing_terminal_or_glob_allow() {
    let missing_terminal = cpex::cpex_core::config::parse_config(
        "plugin_settings: {routing_enabled: true, fail_on_plugin_error: true}\nroutes: [{tool: search}]\n",
    )
    .expect("structurally valid CPEX");
    assert!(PolicyProfile::try_from(missing_terminal).is_err());

    let glob = cpex::cpex_core::config::parse_config(
        "plugin_settings: {routing_enabled: true, fail_on_plugin_error: true}\nroutes: [{tool: 'search*'}, {tool: '*'}, {resource: '*'}, {prompt: '*'}]\n",
    )
    .expect("structurally valid CPEX");
    assert!(PolicyProfile::try_from(glob).is_err());
}
