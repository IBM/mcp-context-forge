use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};

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

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
pub struct PluginViolation {
    #[pyo3(get, set)]
    pub reason: String,
    #[pyo3(get, set)]
    pub description: String,
    #[pyo3(get, set)]
    pub code: String,
    #[pyo3(get, set)]
    pub details: Option<HashMap<String, String>>,
}

#[pyclass]
#[derive(Debug)]
pub struct URLPluginResult {
    #[pyo3(get, set)]
    pub continue_processing: bool,
    #[pyo3(get, set)]
    pub violation: Option<PluginViolation>,
}
