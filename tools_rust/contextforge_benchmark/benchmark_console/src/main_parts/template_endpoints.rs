pub(crate) fn template_endpoints(generator: &GeneratorState) -> String {
    let custom = parse_pipe_lines(generator.get("workload_endpoints"));
    if !custom.is_empty() {
        return format!(
            "[defaults.load.workload]\nselection = \"{}\"\nfallback_endpoint = \"{}\"\n\n{}",
            escape_toml(generator.get("workload_selection")),
            escape_toml(generator.get("fallback_endpoint")),
            custom.join("\n")
        );
    }

    match generator.get("template_kind") {
        "a2a" => format!(
            r#"[defaults.load.workload]
selection = "{}"
fallback_endpoint = "{}"

[defaults.load.workload.endpoints."/health"]
enabled = false

[defaults.load.workload.endpoints."/servers"]
enabled = false

[defaults.load.workload.endpoints."/a2a"]
enabled = false

[defaults.load.workload.endpoints."/a2a/a2a-echo-agent/invoke"]
enabled = true
weight = 1
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
        "mcp" => format!(
            r#"[defaults.load.workload]
selection = "{}"
fallback_endpoint = "{}"

[defaults.load.workload.endpoints."/health"]
enabled = false

[defaults.load.workload.endpoints."/ready"]
enabled = false

[defaults.load.workload.endpoints."/admin/plugins"]
enabled = false

[defaults.load.workload.endpoints."/servers"]
enabled = true
weight = 2

[defaults.load.workload.endpoints."/mcp tools/list"]
enabled = true
weight = 6

[defaults.load.workload.endpoints."/mcp tools/call fast-time-get-system-time"]
enabled = true
weight = 14

[defaults.load.workload.endpoints."/mcp tools/call fast-time-convert-time"]
enabled = true
weight = 12
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
        _ => format!(
            r#"[defaults.load.workload]
# selection = "{}"
fallback_endpoint = "{}"

# Add endpoint tables as needed:
# [defaults.load.workload.endpoints."/health"]
# enabled = true
# weight = 1
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
    }
}
use crate::main_parts::*;
