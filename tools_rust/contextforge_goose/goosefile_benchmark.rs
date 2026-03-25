use std::env;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use goose::goose::{GooseMethod, GooseRequest};
use goose::prelude::*;
use goose_eggs::{validate_page, Validate};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, CONTENT_TYPE};
use serde::Deserialize;
use serde_json::Value;

static REQUEST_PLAN: OnceLock<Vec<RequestPlanEntry>> = OnceLock::new();
static RNG: OnceLock<Mutex<StdRng>> = OnceLock::new();
static REQUEST_COUNT: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Debug, Deserialize)]
struct RequestPlanEntry {
    name: String,
    weight: usize,
    request: RequestDefinition,
}

#[derive(Clone, Debug, Deserialize)]
struct RequestDefinition {
    kind: String,
    path: Option<String>,
    payload: Option<Value>,
    auth: Option<bool>,
    server_id: Option<String>,
    expect_json: Option<bool>,
    expect_list_min_items: Option<usize>,
    expect_list_item_name: Option<String>,
    expect_result_key: Option<String>,
    expect_result_min_items: Option<usize>,
    expect_content_text: Option<bool>,
}

fn request_plan() -> &'static Vec<RequestPlanEntry> {
    REQUEST_PLAN.get_or_init(|| {
        serde_json::from_str(&env::var("BENCH_REQUEST_PLAN").unwrap_or_else(|_| "[]".to_string()))
            .unwrap_or_default()
    })
}

fn benchmark_rng() -> &'static Mutex<StdRng> {
    RNG.get_or_init(|| {
        let seed = env::var("BENCH_SEED")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(42);
        Mutex::new(StdRng::seed_from_u64(seed))
    })
}

fn choose_entry() -> Option<RequestPlanEntry> {
    let plan = request_plan();
    if plan.is_empty() {
        return None;
    }
    let total_weight: usize = plan.iter().map(|entry| entry.weight.max(1)).sum();
    let mut rng = benchmark_rng().lock().expect("benchmark rng poisoned");
    let needle = rng.gen_range(0..total_weight);
    let mut offset = 0usize;
    for entry in plan {
        offset += entry.weight.max(1);
        if needle < offset {
            return Some(entry.clone());
        }
    }
    plan.last().cloned()
}

fn request_limit_reached() -> bool {
    let limit = env::var("BENCH_REQUEST_COUNT")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(0);
    if limit == 0 {
        return false;
    }
    REQUEST_COUNT.fetch_add(1, Ordering::Relaxed) >= limit
}

fn auth_header() -> Option<HeaderValue> {
    let token = env::var("MCPGATEWAY_BEARER_TOKEN").unwrap_or_default();
    if token.trim().is_empty() {
        return None;
    }
    HeaderValue::from_str(&format!("Bearer {}", token.trim())).ok()
}

fn add_common_headers(headers: &mut HeaderMap, definition: &RequestDefinition) {
    headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
    if matches!(definition.kind.as_str(), "post" | "rpc" | "mcp") {
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    }
    if definition.auth.unwrap_or(false) {
        if let Some(value) = auth_header() {
            headers.insert(AUTHORIZATION, value);
        }
    }
}

fn mcp_path(definition: &RequestDefinition) -> String {
    let server_id = definition
        .server_id
        .clone()
        .unwrap_or_else(|| "9779b6698cbd4b4995ee04a4fab38737".to_string());
    format!("/servers/{server_id}/mcp")
}

async fn send_named_json_request(
    user: &mut GooseUser,
    method: GooseMethod,
    path: &str,
    name: &str,
    payload: Option<&Value>,
    definition: &RequestDefinition,
) -> Result<goose::goose::GooseResponse, Box<TransactionError>> {
    let mut headers = HeaderMap::new();
    add_common_headers(&mut headers, definition);
    let mut request_builder = user.get_request_builder(&method, path)?;
    request_builder = request_builder.headers(headers);
    if let Some(body) = payload {
        request_builder = request_builder.json(body);
    }
    let request = GooseRequest::builder()
        .method(method)
        .path(path)
        .name(name)
        .set_request_builder(request_builder)
        .build();
    user.request(request).await
}

async fn initialize_mcp_session(user: &mut GooseUser, definition: &RequestDefinition) -> TransactionResult {
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": "benchmark-init",
        "method": "initialize",
        "params": {
            "protocolVersion": env::var("BENCH_MCP_PROTOCOL_VERSION").unwrap_or_else(|_| "2024-11-05".to_string()),
            "capabilities": {},
            "clientInfo": {"name": "benchmark-goose", "version": "1.0"}
        }
    });
    let goose = send_named_json_request(
        user,
        GooseMethod::Post,
        &mcp_path(definition),
        "/mcp initialize [setup]",
        Some(&payload),
        definition,
    )
    .await?;
    let validate = Validate::builder().status(200).build();
    let _ = validate_page(user, goose, &validate).await?;
    Ok(())
}

fn validate_json_body(body: &str, entry: &RequestPlanEntry) -> Result<(), String> {
    let payload: Value = serde_json::from_str(body).map_err(|error| format!("invalid json: {error}"))?;
    let definition = &entry.request;
    let root = if matches!(definition.kind.as_str(), "rpc" | "mcp") {
        if payload.get("error").is_some() {
            return Err("json-rpc response included error".to_string());
        }
        payload
            .get("result")
            .ok_or_else(|| "json-rpc response missing result".to_string())?
            .clone()
    } else {
        payload
    };

    if let Some(min_items) = definition.expect_list_min_items {
        let items = root.as_array().ok_or_else(|| "expected list response".to_string())?;
        if items.len() < min_items {
            return Err(format!("expected at least {min_items} list items"));
        }
    }
    if let Some(expected_name) = &definition.expect_list_item_name {
        let items = root.as_array().ok_or_else(|| "expected list response".to_string())?;
        let found = items.iter().any(|item| item.get("name").and_then(Value::as_str) == Some(expected_name.as_str()));
        if !found {
            return Err(format!("expected item named {expected_name}"));
        }
    }
    if let Some(expected_key) = &definition.expect_result_key {
        let result = root.as_object().ok_or_else(|| "expected object response".to_string())?;
        let value = result
            .get(expected_key)
            .ok_or_else(|| format!("expected result key '{expected_key}'"))?;
        if let Some(min_items) = definition.expect_result_min_items {
            let items = value.as_array().ok_or_else(|| format!("expected array at result.{expected_key}"))?;
            if items.len() < min_items {
                return Err(format!("expected at least {min_items} items in result.{expected_key}"));
            }
        }
    }
    if definition.expect_content_text.unwrap_or(false) {
        let content = root
            .get("content")
            .and_then(Value::as_array)
            .ok_or_else(|| "expected content array".to_string())?;
        let has_text = content.iter().any(|item| item.get("text").and_then(Value::as_str).is_some());
        if !has_text {
            return Err("expected text content".to_string());
        }
    }
    Ok(())
}

async fn execute_entry(user: &mut GooseUser) -> TransactionResult {
    if request_limit_reached() {
        tokio::time::sleep(Duration::from_millis(50)).await;
        return Ok(());
    }

    let Some(entry) = choose_entry() else {
        return Ok(());
    };
    let definition = &entry.request;
    let goose = match definition.kind.as_str() {
        "get" => {
            send_named_json_request(
                user,
                GooseMethod::Get,
                definition.path.as_deref().unwrap_or("/"),
                &entry.name,
                None,
                definition,
            )
            .await?
        }
        "post" | "rpc" => {
            send_named_json_request(
                user,
                GooseMethod::Post,
                definition.path.as_deref().unwrap_or("/rpc"),
                &entry.name,
                definition.payload.as_ref(),
                definition,
            )
            .await?
        }
        "mcp" => {
            initialize_mcp_session(user, definition).await?;
            send_named_json_request(
                user,
                GooseMethod::Post,
                &mcp_path(definition),
                &entry.name,
                definition.payload.as_ref(),
                definition,
            )
            .await?
        }
        other => unreachable!("unsupported request kind: {other}"),
    };

    let validate = Validate::builder().status(200).build();
    let mut request_metric = goose.request.clone();
    let body = validate_page(user, goose, &validate).await?;
    if definition.expect_json.unwrap_or(false)
        || matches!(definition.kind.as_str(), "rpc" | "mcp")
        || definition.expect_result_key.is_some()
        || definition.expect_content_text.unwrap_or(false)
    {
        if let Err(error) = validate_json_body(&body, &entry) {
            return user.set_failure(&error, &mut request_metric, None, Some(&body));
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), GooseError> {
    let scenario = scenario!("ContextForgeBenchmark")
        .set_wait_time(Duration::from_millis(0), Duration::from_millis(0))?
        .register_transaction(transaction!(execute_entry));

    GooseAttack::initialize()?.register_scenario(scenario).execute().await?;
    Ok(())
}
