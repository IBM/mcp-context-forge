use std::{collections::BTreeSet, path::Path, process::Command};

use praxis_core::config::{Config, FailureMode, FilterEntry};
use praxis_filter::{FilterPipeline, FilterRegistry};
use serde::Deserialize;
use tempfile::TempDir;

const GOLDEN_FIXTURE: &str =
    include_str!("../../../tests/fixtures/praxis_config/bundle-render-v1.json");
const PROBE_ENV: &str = "PRAXIS_TASK5_NATIVE_PROBE";
const EXPECTED_ERROR_ENV: &str = "PRAXIS_TASK5_EXPECTED_ERROR";

#[derive(Clone, Copy)]
enum GenerationMutation {
    Valid,
    ConditionalCpex,
    DuplicateMapping,
    FailOpenCpex,
    InvalidFilter,
    InvalidPolicyPath,
    InvalidRoot,
    UnknownEntity,
}

#[derive(Deserialize)]
struct GoldenBundle {
    documents: Vec<GoldenDocument>,
}

#[derive(Deserialize)]
struct GoldenDocument {
    content_utf8: String,
    path: String,
}

#[derive(Deserialize)]
struct DispatcherConfig {
    policies: Vec<PolicyMapping>,
}

#[derive(Deserialize)]
struct PolicyMapping {
    config_path: String,
}

fn mutate_document(document: &GoldenDocument, mutation: GenerationMutation) -> String {
    match (document.path.as_str(), mutation) {
        ("praxis.yaml", GenerationMutation::ConditionalCpex) => document.content_utf8.replace(
            "{\"filter\":\"cpex\",",
            "{\"filter\":\"cpex\",\"conditions\":[{\"when\":{\"path_prefix\":\"/servers\"}}],",
        ),
        ("praxis.yaml", GenerationMutation::DuplicateMapping) => document.content_utf8.replacen(
            "\"config_path\":\"cpex/team-red--server-team.yaml\",\"server_id\":\"server-team\"",
            "\"config_path\":\"cpex/platform--server-public.yaml\",\"server_id\":\"server-public\"",
            1,
        ),
        ("praxis.yaml", GenerationMutation::FailOpenCpex) => document.content_utf8.replace(
            "{\"filter\":\"cpex\",",
            "{\"filter\":\"cpex\",\"failure_mode\":\"open\",",
        ),
        ("praxis.yaml", GenerationMutation::InvalidFilter) => {
            document
                .content_utf8
                .replacen("\"filter\":\"mcp\"", "\"filter\":\"unknown\"", 1)
        }
        ("praxis.yaml", GenerationMutation::InvalidPolicyPath) => document.content_utf8.replacen(
            "cpex/platform--server-public.yaml",
            "../platform--server-public.yaml",
            1,
        ),
        ("praxis.yaml", GenerationMutation::InvalidRoot) => "{\"routes\":[]}\n".to_owned(),
        ("cpex/platform--server-public.yaml", GenerationMutation::UnknownEntity) => document
            .content_utf8
            .replacen("\"tool\":\"clock\"", "\"llm\":\"clock\"", 1),
        (_, _) => document.content_utf8.clone(),
    }
}

fn materialize_generation(mutation: GenerationMutation) -> TempDir {
    let generation = tempfile::tempdir().expect("temporary immutable generation");
    let fixture: GoldenBundle =
        serde_json::from_str(GOLDEN_FIXTURE).expect("committed golden fixture");
    for document in fixture.documents {
        let destination = generation.path().join(&document.path);
        std::fs::create_dir_all(destination.parent().expect("document parent"))
            .expect("create generation directory");
        std::fs::write(destination, mutate_document(&document, mutation))
            .expect("write generated document");
    }
    generation
}

fn validate_security_entry(entry: &FilterEntry, registry: &FilterRegistry) -> Result<(), String> {
    if registry.is_security_filter(&entry.filter_type)
        && (!entry.conditions.is_empty() || !entry.response_conditions.is_empty())
    {
        return Err(format!(
            "security filter '{}' must be unconditional",
            entry.filter_type
        ));
    }
    if registry.is_security_filter(&entry.filter_type) && entry.failure_mode == FailureMode::Open {
        return Err(format!(
            "security filter '{}' must fail closed",
            entry.filter_type
        ));
    }
    Ok(())
}

fn policy_paths(entries: &[FilterEntry]) -> Result<BTreeSet<String>, String> {
    let cpex = entries
        .iter()
        .find(|entry| entry.filter_type == "cpex")
        .ok_or_else(|| "missing cpex filter".to_owned())?;
    let config: DispatcherConfig =
        serde_yaml::from_value(cpex.config.clone()).map_err(|error| error.to_string())?;
    Ok(config
        .policies
        .into_iter()
        .map(|mapping| mapping.config_path)
        .collect())
}

fn generated_policy_paths() -> Result<BTreeSet<String>, String> {
    std::fs::read_dir("cpex")
        .map_err(|error| error.to_string())?
        .map(|entry| {
            let path = entry.map_err(|error| error.to_string())?.path();
            let file_name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| "generated CPEX filename must be UTF-8".to_owned())?;
            Ok(format!("cpex/{file_name}"))
        })
        .collect()
}

fn validate_generation_from_cwd() -> Result<(), String> {
    let config = Config::from_file(Path::new("praxis.yaml")).map_err(|error| error.to_string())?;
    let mut registry = FilterRegistry::with_builtins();
    praxis_cf_dataplane::register_filters(&mut registry);
    if !registry.is_security_filter("cpex") {
        return Err("cpex filter must remain security-classified".to_owned());
    }
    match config.listeners.as_slice() {
        [listener] if listener.filter_chains == ["mcp"] => {}
        _ => return Err("Task 5 listener must reference only the mcp filter chain".to_owned()),
    }
    let chain = config
        .filter_chains
        .iter()
        .find(|chain| chain.name == "mcp")
        .ok_or_else(|| "missing mcp filter chain".to_owned())?;
    for entry in &chain.filters {
        validate_security_entry(entry, &registry)?;
    }
    let mut entries = chain.filters.clone();
    let pipeline =
        FilterPipeline::build(&mut entries, &registry).map_err(|error| error.to_string())?;
    if policy_paths(&chain.filters)? != generated_policy_paths()? {
        return Err("root policy mappings must exactly match generated CPEX files".to_owned());
    }
    let errors = pipeline.ordering_errors(
        &entries,
        false,
        &config.insecure_options.skip_pipeline_checks,
    );
    if !errors.is_empty() {
        return Err(errors.join("; "));
    }
    Ok(())
}

fn run_probe(mutation: GenerationMutation, expected_error: Option<&str>) {
    let generation = materialize_generation(mutation);
    let mut command = Command::new(std::env::current_exe().expect("native test executable"));
    command
        .current_dir(generation.path())
        .args([
            "--exact",
            "task5_native_probe_from_generation_cwd",
            "--nocapture",
        ])
        .env(PROBE_ENV, "1");
    if let Some(expected) = expected_error {
        command.env(EXPECTED_ERROR_ENV, expected);
    }
    let output = command.output().expect("run native compatibility probe");
    assert!(
        output.status.success(),
        "native probe failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn task5_native_probe_from_generation_cwd() {
    if std::env::var_os(PROBE_ENV).is_none() {
        return;
    }
    let result = validate_generation_from_cwd();
    match std::env::var(EXPECTED_ERROR_ENV) {
        Ok(expected) => {
            let error = result.expect_err("mutated generation must fail native validation");
            assert!(
                error.contains(&expected),
                "expected native validation error containing {expected:?}, got {error:?}"
            );
        }
        Err(_) => result.expect("valid committed Task 5 generation"),
    }
}

#[test]
fn task5_native_compat_accepts_committed_generation() {
    run_probe(GenerationMutation::Valid, None);
}

#[test]
fn task5_native_compat_rejects_invalid_policy_path() {
    run_probe(
        GenerationMutation::InvalidPolicyPath,
        Some("invalid policy path"),
    );
}

#[test]
fn task5_native_compat_rejects_duplicate_mapping() {
    run_probe(
        GenerationMutation::DuplicateMapping,
        Some("duplicate server id"),
    );
}

#[test]
fn task5_native_compat_rejects_unknown_entity() {
    run_probe(
        GenerationMutation::UnknownEntity,
        Some("invalid CPEX policy profile"),
    );
}

#[test]
fn task5_native_compat_rejects_invalid_root_schema() {
    run_probe(GenerationMutation::InvalidRoot, Some("invalid YAML"));
}

#[test]
fn task5_native_compat_rejects_invalid_filter_schema() {
    run_probe(
        GenerationMutation::InvalidFilter,
        Some("unknown filter type"),
    );
}

#[test]
fn task5_native_compat_rejects_conditional_cpex() {
    run_probe(
        GenerationMutation::ConditionalCpex,
        Some("must be unconditional"),
    );
}

#[test]
fn task5_native_compat_rejects_fail_open_cpex() {
    run_probe(GenerationMutation::FailOpenCpex, Some("must fail closed"));
}
