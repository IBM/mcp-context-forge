use pyo3::{prelude::*, types::PyDict};
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

impl URLReputationConfig {
    /// Normalize domains to lowercase for case-insensitive matching
    pub fn normalize_domains(mut self) -> Self {
        self.whitelist_domains = self.whitelist_domains.into_iter().map(|d| d.to_lowercase()).collect();
        self.blocked_domains = self.blocked_domains.into_iter().map(|d| d.to_lowercase()).collect();
        self
    }
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

impl PluginViolation {
    pub fn to_py_dict(&self, py: Python) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("reason", &self.reason)?;
        dict.set_item("description", &self.description)?;
        dict.set_item("code", &self.code)?;
        match &self.details {
            Some(details) => dict.set_item("details", details)?,
            None => dict.set_item("details", py.None())?,
        }
        Ok(dict.into())
    }
}

impl URLPluginResult {
    pub fn to_py_dict(&self, py: Python) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("continue_processing", self.continue_processing)?;
        match &self.violation {
            Some(v) => dict.set_item("violation", v.to_py_dict(py)?)?,
            None => dict.set_item("violation", py.None())?,
        }
        Ok(dict.into())
    }
}
