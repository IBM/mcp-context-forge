use std::collections::{HashMap, HashSet};
use pyo3::prelude::*;

#[pyclass]
#[derive(FromPyObject)]
pub struct URLReputationConfig {
    pub whitelist_domains: HashSet<String>,
    pub allowed_patterns: Vec<String>,
    pub blocked_domains: HashSet<String>,
    pub blocked_patterns: Vec<String>,
    pub use_heuristic_check: bool,
    pub entropy_threshold: f32,
    pub block_non_secure_http: bool,
}

#[pyclass]
pub struct PluginViolation {
    pub reason: String,
    pub description: String,
    pub code: String,
    pub details: Option<HashMap<String, String>>,
}

#[pyclass]
pub struct URLPluginResult {
    pub continue_processing: bool,
    pub violation: Option<PluginViolation>,
}

