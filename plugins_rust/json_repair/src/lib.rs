// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use pyo3::prelude::*;
use regex::Regex;

/// Rust-backed JSON repair helper exposed to Python via PyO3.
#[pyclass]
pub struct JSONRepairPluginRust {
    /// Matches JSON-ish bracketed text (`{...}` or `[...]`), including multiline.
    json_brackets_re: Regex,
    /// Matches commas that appear immediately before `}` or `]`.
    trailing_comma_re: Regex,
}

#[pymethods]
impl JSONRepairPluginRust {
    /// Build a repair helper with precompiled patterns.
    #[new]
    pub fn new() -> PyResult<Self> {
        let json_brackets_re = Regex::new(r"(?s)^[\[{].*[\]}]$").map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid regex pattern: {}", e))
        })?;
        let trailing_comma_re = Regex::new(r",(\s*[}\]])").map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid regex pattern: {}", e))
        })?;

        Ok(Self {
            json_brackets_re,
            trailing_comma_re,
        })
    }

    /// Attempt conservative repair for near-JSON text.
    ///
    /// Returns `Some(repaired_json)` only when the repaired output parses as valid JSON.
    /// Returns `None` if input is already valid JSON or no safe repair is found.
    pub fn repair(&self, text: &str) -> Option<String> {
        let t = text.trim();

        if Self::try_parse(t) {
            return None;
        }

        let mut base = t.to_string();

        // Only normalize single quotes when input already looks like structured JSON.
        if self.json_brackets_re.is_match(t) && t.contains('\'') && !t.contains('"') {
            base = t.replace('\'', "\"");
            if Self::try_parse(&base) {
                return Some(base);
            }
        }

        let repaired = self.trailing_comma_re.replace_all(&base, "$1").to_string();

        if repaired != base && Self::try_parse(&repaired) {
            return Some(repaired);
        }

        // Mirror Python plugin behavior: wrap object-like text missing outer braces.
        if !t.starts_with('{') && t.contains(':') && !t.contains('{') && !t.contains('}') {
            let wrapped = format!("{{{}}}", t);
            if Self::try_parse(&wrapped) {
                return Some(wrapped);
            }
        }
        None
    }
}

impl JSONRepairPluginRust {
    /// Fast validity check used to gate conservative repairs.
    fn try_parse(s: &str) -> bool {
        serde_json::from_str::<serde_json::Value>(s).is_ok()
    }
}

/// Python module entrypoint.
#[pymodule]
fn json_repair(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<JSONRepairPluginRust>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::JSONRepairPluginRust;

    #[test]
    fn already_valid_json_returns_none() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = r#"{"a": 1, "b": 2}"#;
        assert_eq!(plugin.repair(input), None);
    }

    #[test]
    fn trailing_comma_repairs_to_valid_json() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = r#"{"a": 1, "b": 2,}"#;
        let repaired = plugin.repair(input).expect("expected a repair");
        assert_eq!(repaired, r#"{"a": 1, "b": 2}"#);
        assert!(JSONRepairPluginRust::try_parse(&repaired));
    }

    #[test]
    fn single_quotes_repairs_when_jsonish_guard_matches() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = "{'a': 1, 'b': 2}";
        let repaired = plugin.repair(input).expect("expected a repair");
        assert_eq!(repaired, r#"{"a": 1, "b": 2}"#);
        assert!(JSONRepairPluginRust::try_parse(&repaired));
    }

    #[test]
    fn unrepairable_input_returns_none() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = "not-json-at-all";
        assert_eq!(plugin.repair(input), None);
    }

    #[test]
    fn wraps_object_like_text_without_outer_braces() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = r#""a": 1, "b": 2"#;
        let repaired = plugin.repair(input).expect("expected a repair");
        assert_eq!(repaired, r#"{"a": 1, "b": 2}"#);
        assert!(JSONRepairPluginRust::try_parse(&repaired));
    }

    #[test]
    fn single_quotes_repair_works_for_multiline_jsonish_text() {
        let plugin = JSONRepairPluginRust::new().expect("plugin init");
        let input = "{\n'a': 1,\n'b': 2\n}";
        let repaired = plugin.repair(input).expect("expected a repair");
        assert_eq!(repaired, "{\n\"a\": 1,\n\"b\": 2\n}");
        assert!(JSONRepairPluginRust::try_parse(&repaired));
    }
}
