use std::collections::BTreeSet;
use std::env;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

use praxis_core::config::{Config, FailureMode, FilterEntry};
use praxis_filter::{FilterPipeline, FilterRegistry};
use serde::Deserialize;
use thiserror::Error;

static CWD_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Error)]
pub enum GenerationValidationError {
    #[error("bundle path is not a readable directory")]
    BundlePath,
    #[error("bundle root configuration is invalid")]
    RootConfig,
    #[error("bundle filter configuration is invalid")]
    FilterConfig,
    #[error("bundle security filter contract is invalid")]
    SecurityContract,
    #[error("bundle policy references do not match its CPEX files")]
    PolicyReferences,
}

#[derive(Deserialize)]
struct DispatcherConfig {
    policies: Vec<PolicyMapping>,
}

#[derive(Deserialize)]
struct PolicyMapping {
    config_path: String,
}

struct CwdGuard {
    original: PathBuf,
    _lock: MutexGuard<'static, ()>,
}

impl CwdGuard {
    fn enter(path: &Path) -> Result<Self, GenerationValidationError> {
        let lock = CWD_LOCK
            .lock()
            .map_err(|_| GenerationValidationError::BundlePath)?;
        let original = env::current_dir().map_err(|_| GenerationValidationError::BundlePath)?;
        env::set_current_dir(path).map_err(|_| GenerationValidationError::BundlePath)?;
        Ok(Self {
            original,
            _lock: lock,
        })
    }
}

impl Drop for CwdGuard {
    fn drop(&mut self) {
        let _ = env::set_current_dir(&self.original);
    }
}

pub fn validate_generation(root: &Path) -> Result<(), GenerationValidationError> {
    let _cwd = CwdGuard::enter(root)?;
    let config = Config::from_file(Path::new("praxis.yaml"))
        .map_err(|_| GenerationValidationError::RootConfig)?;
    let mut registry = FilterRegistry::with_builtins();
    crate::register_filters(&mut registry);
    let chain = match config.filter_chains.as_slice() {
        [chain] if chain.name == "mcp" => chain,
        _ => return Err(GenerationValidationError::FilterConfig),
    };
    match config.listeners.as_slice() {
        [listener] if listener.filter_chains == ["mcp"] => {}
        _ => return Err(GenerationValidationError::FilterConfig),
    }
    for entry in &chain.filters {
        validate_security_entry(entry, &registry)?;
    }
    let mut entries = chain.filters.clone();
    let pipeline = FilterPipeline::build(&mut entries, &registry)
        .map_err(|_| GenerationValidationError::FilterConfig)?;
    if policy_paths(&chain.filters)? != generated_policy_paths()? {
        return Err(GenerationValidationError::PolicyReferences);
    }
    if pipeline
        .ordering_errors(
            &entries,
            false,
            &config.insecure_options.skip_pipeline_checks,
        )
        .is_empty()
    {
        Ok(())
    } else {
        Err(GenerationValidationError::SecurityContract)
    }
}

fn validate_security_entry(
    entry: &FilterEntry,
    registry: &FilterRegistry,
) -> Result<(), GenerationValidationError> {
    if registry.is_security_filter(&entry.filter_type)
        && (!entry.conditions.is_empty() || !entry.response_conditions.is_empty())
    {
        return Err(GenerationValidationError::SecurityContract);
    }
    if registry.is_security_filter(&entry.filter_type) && entry.failure_mode == FailureMode::Open {
        return Err(GenerationValidationError::SecurityContract);
    }
    Ok(())
}

fn policy_paths(entries: &[FilterEntry]) -> Result<BTreeSet<String>, GenerationValidationError> {
    let cpex = entries
        .iter()
        .find(|entry| entry.filter_type == "cpex")
        .ok_or(GenerationValidationError::SecurityContract)?;
    let config: DispatcherConfig = serde_yaml::from_value(cpex.config.clone())
        .map_err(|_| GenerationValidationError::FilterConfig)?;
    Ok(config
        .policies
        .into_iter()
        .map(|mapping| mapping.config_path)
        .collect())
}

fn generated_policy_paths() -> Result<BTreeSet<String>, GenerationValidationError> {
    let mut paths = BTreeSet::new();
    for entry in
        std::fs::read_dir("cpex").map_err(|_| GenerationValidationError::PolicyReferences)?
    {
        let path = entry
            .map_err(|_| GenerationValidationError::PolicyReferences)?
            .path();
        if !path.is_file() {
            continue;
        }
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or(GenerationValidationError::PolicyReferences)?;
        paths.insert(format!("cpex/{name}"));
    }
    Ok(paths)
}
