use crate::build_error::build_error;
use crate::matcher::Matcher;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use regex::{RegexSet, escape};

#[gen_stub_pyclass]
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct DenyListRs {
    rs: RegexSet,
}

impl Matcher for DenyListRs {
    /// implements matching with regex set
    fn is_match(&self, s: &str) -> bool {
        // Convert input to lowercase for case-insensitive matching
        self.rs.is_match(&s.to_lowercase())
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl DenyListRs {
    /// constructor
    /// # Errors
    /// * regex problems (should not happen with simple match)
    #[new]
    pub fn new(words: Vec<String>) -> PyResult<Self> {
        // Store deny words in lowercase for case-insensitive matching
        let patterns: Vec<String> = words
            .into_iter()
            .map(|w| escape(&w.to_lowercase()))
            .collect();

        let rs = RegexSet::new(patterns).map_err(build_error)?;

        Ok(Self { rs })
    }
    #[must_use]
    pub fn is_match(&self, s: &str) -> bool {
        Matcher::is_match(self, s)
    }
    #[must_use]
    pub fn scan_str(&self, txt: &str) -> bool {
        Matcher::scan_str(self, txt)
    }
    #[must_use]
    pub fn scan(&self, args: &Bound<'_, PyDict>) -> bool {
        Matcher::scan(self, args)
    }
    #[must_use]
    pub fn scan_any(&self, value: &Bound<'_, PyAny>) -> bool {
        Matcher::scan_any(self, value)
    }
}
