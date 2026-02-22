use aho_corasick::{AhoCorasick, MatchKind};
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::build_error::build_error;
use crate::matcher::Matcher;
use pyo3::pyclass;
use pyo3::types::PyDict;

#[gen_stub_pyclass]
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct DenyList {
    pub ac: AhoCorasick,
}

impl Matcher for DenyList {
    /// implements match with aho-corasic
    fn is_match(&self, s: &str) -> bool {
        // Convert input to lowercase for case-insensitive matching
        self.ac.is_match(&s.to_lowercase())
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl DenyList {
    /// constructor
    /// # Errors
    /// * aho-corasic errors (too long patterns)
    #[new]
    pub fn new(words: Vec<String>) -> PyResult<Self> {
        // Store deny words in lowercase for case-insensitive matching
        let words_lower: Vec<String> = words.into_iter().map(|w| w.to_lowercase()).collect();

        let ac = AhoCorasick::builder()
            .match_kind(MatchKind::LeftmostFirst)
            .build(words_lower)
            .map_err(build_error)?;

        Ok(Self { ac })
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
    /// scans dict,str,list
    #[must_use]
    pub fn scan_any(&self, value: &Bound<'_, PyAny>) -> bool {
        Matcher::scan_any(self, value)
    }
}
