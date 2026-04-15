use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde_json::{Value, json};

use crate::{RequestDefinition, RequestSpec, WorkloadConfig};

fn payload_root(root: &Path) -> PathBuf {
    root.join("crates/contextforge_benchmark_runner/assets/payloads")
}

fn load_payload(root: &Path, group: &str, name: &str) -> Result<Value> {
    let path = payload_root(root).join(group).join(name);
    let raw =
        fs::read_to_string(&path).with_context(|| format!("failed to read {}", path.display()))?;
    Ok(
        serde_json::from_str(&raw)
            .with_context(|| format!("failed to parse {}", path.display()))?,
    )
}

pub fn benchmark_catalog(root: &Path) -> Result<Vec<RequestDefinition>> {
    let default_server = "9779b6698cbd4b4995ee04a4fab38737".to_string(); // pragma: allowlist secret
    Ok(vec![
        RequestDefinition {
            name: "/health".into(),
            group: "health".into(),
            tags: set(&["health"]),
            weight: 10,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/health".into()),
                payload: None,
                auth: false,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/ready".into(),
            group: "health".into(),
            tags: set(&["health"]),
            weight: 4,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/ready".into()),
                payload: None,
                auth: false,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/admin/plugins".into(),
            group: "admin".into(),
            tags: set(&["admin", "plugins"]),
            weight: 2,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/admin/plugins".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/servers".into(),
            group: "servers".into(),
            tags: set(&["servers", "rest", "discovery"]),
            weight: 5,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/servers".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: Some("Fast Time Server".into()),
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/a2a".into(),
            group: "a2a".into(),
            tags: set(&["a2a", "rest", "discovery"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/a2a".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: Some("a2a-echo-agent".into()),
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/a2a/a2a-echo-agent/invoke".into(),
            group: "a2a".into(),
            tags: set(&["a2a", "invoke", "echo"]),
            weight: 8,
            request: RequestSpec {
                kind: "post".into(),
                path: Some("/a2a/a2a-echo-agent/invoke".into()),
                payload: Some(
                    json!({"parameters":{"message":{"kind":"message","role":"user","messageId":"benchmark-a2a-invoke","parts":[{"kind":"text","text":"benchmark ping"}]}},"interaction_type":"query"}),
                ),
                auth: true,
                server_id: None,
                expect_result_key: Some("result".into()),
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "tools", "discovery"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "list_tools.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("tools".into()),
                expect_result_min_items: Some(2),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/call fast-time-get-system-time".into(),
            group: "tools".into(),
            tags: set(&["tools", "mcp", "plugin-heavy"]),
            weight: 8,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "get_system_time.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(true),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/call fast-time-convert-time".into(),
            group: "tools".into(),
            tags: set(&["tools", "mcp", "plugin-heavy"]),
            weight: 6,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "convert_time.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(true),
                name: None,
            },
        },
        RequestDefinition {
            name: "/resources".into(),
            group: "resources".into(),
            tags: set(&["resources", "rest"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/resources".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "resources"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "list_resources.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("resources".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/read timezone://info".into(),
            group: "resources".into(),
            tags: set(&["resources", "mcp", "plugin-heavy"]),
            weight: 5,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "read_timezone_info.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("contents".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/read time://current/world".into(),
            group: "resources".into(),
            tags: set(&["resources", "mcp", "plugin-heavy"]),
            weight: 4,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "read_world_times.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("contents".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/prompts".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "rest"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/prompts".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "prompts"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "list_prompts.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("prompts".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/get fast-time-schedule-meeting".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "mcp", "plugin-heavy"]),
            weight: 5,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "get_schedule_meeting.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("messages".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/get fast-time-compare-timezones".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "mcp", "plugin-heavy"]),
            weight: 4,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "get_compare_timezones.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("messages".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
    ])
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|item| (*item).to_string()).collect()
}

pub fn benchmark_request_names(root: &Path) -> Result<BTreeSet<String>> {
    Ok(benchmark_catalog(root)?
        .into_iter()
        .map(|request| request.name)
        .collect())
}

pub fn resolve_requests_from_workload(
    root: &Path,
    workload: &WorkloadConfig,
) -> Result<Vec<RequestDefinition>> {
    let catalog = benchmark_catalog(root)?;
    if workload.endpoints.is_empty() {
        return Ok(catalog);
    }
    let mut requests = Vec::new();
    for request in catalog.iter() {
        if let Some(override_config) = workload.endpoints.get(&request.name) {
            let enabled = override_config.enabled.unwrap_or(true);
            let weight = override_config.weight.unwrap_or(request.weight);
            if enabled && weight > 0 {
                let mut resolved = request.clone();
                resolved.weight = weight;
                requests.push(resolved);
            }
        }
    }
    if !requests.is_empty() {
        return Ok(requests);
    }
    let fallback = workload.fallback_endpoint.as_deref().unwrap_or("/health");
    Ok(catalog
        .into_iter()
        .filter(|request| request.name == fallback)
        .collect())
}
