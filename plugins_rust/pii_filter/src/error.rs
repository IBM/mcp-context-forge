// SPDX-License-Identifier: Apache-2.0
//! Crate-wide error types for config, pattern compilation, and masking.

use pyo3::{PyErr, Python};
use regex::Error as RegexError;
use thiserror::Error;

#[non_exhaustive]
#[derive(Debug, Error)]
pub enum MaskError {
    #[error("Invalid detection span for masking (start={start}, end={end}, text_len={text_len})")]
    InvalidSpan {
        start: usize,
        end: usize,
        text_len: usize,
    },

    #[error("Invalid UTF-8 boundary for masking (start={start}, end={end})")]
    InvalidUtf8Boundary { start: usize, end: usize },
}

#[non_exhaustive]
#[derive(Debug, Error)]
pub enum PatternError {
    #[error("Failed to compile regex pattern '{pattern}': {source}")]
    RegexCompile { pattern: String, source: RegexError },

    #[error("Failed to compile RegexSet: {source}")]
    RegexSetCompile { source: RegexError },

    #[error("Invalid whitelist pattern '{pattern}': {source}")]
    WhitelistCompile { pattern: String, source: RegexError },
}

#[non_exhaustive]
#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("Missing required field '{field}'")]
    MissingField { field: &'static str },

    #[error("Invalid value for field '{field}': {details}")]
    InvalidField {
        field: &'static str,
        details: String,
    },
}

#[non_exhaustive]
#[derive(Debug, Error)]
pub enum BlockError {
    #[error("PII detection blocked content processing ({count} detection(s): {pii_types})")]
    DetectionBlocked { count: usize, pii_types: String },
}

#[non_exhaustive]
#[derive(Debug, Error)]
pub enum PIIFilterError {
    #[error(transparent)]
    Config(#[from] ConfigError),

    #[error(transparent)]
    Pattern(#[from] PatternError),

    #[error(transparent)]
    Mask(#[from] MaskError),

    #[error(transparent)]
    Block(#[from] BlockError),

    #[error(transparent)]
    Python(#[from] PyErr),
}

impl PIIFilterError {
    pub fn category(&self) -> &'static str {
        match self {
            PIIFilterError::Config(_) => "config",
            PIIFilterError::Pattern(_) => "pattern",
            PIIFilterError::Mask(_) => "mask",
            PIIFilterError::Block(_) => "block",
            PIIFilterError::Python(_) => "python",
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            PIIFilterError::Config(ConfigError::MissingField { .. }) => "missing_field",
            PIIFilterError::Config(ConfigError::InvalidField { .. }) => "invalid_field",
            PIIFilterError::Pattern(PatternError::RegexCompile { .. }) => "regex_compile",
            PIIFilterError::Pattern(PatternError::RegexSetCompile { .. }) => "regex_set_compile",
            PIIFilterError::Pattern(PatternError::WhitelistCompile { .. }) => "whitelist_compile",
            PIIFilterError::Mask(MaskError::InvalidSpan { .. }) => "invalid_span",
            PIIFilterError::Mask(MaskError::InvalidUtf8Boundary { .. }) => "invalid_utf8_boundary",
            PIIFilterError::Block(BlockError::DetectionBlocked { .. }) => "detection_blocked",
            PIIFilterError::Python(_) => "python_exception",
        }
    }

    pub fn safe_field_name(&self) -> Option<&'static str> {
        match self {
            PIIFilterError::Config(ConfigError::MissingField { field })
            | PIIFilterError::Config(ConfigError::InvalidField { field, .. }) => Some(field),
            _ => None,
        }
    }

    pub fn to_py_err(&self) -> PyErr {
        match self {
            PIIFilterError::Python(err) => Python::attach(|py| err.clone_ref(py)),
            PIIFilterError::Config(_) | PIIFilterError::Pattern(_) => {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(self.to_string())
            }
            PIIFilterError::Mask(_) | PIIFilterError::Block(_) => {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(self.to_string())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use regex::RegexSet;

    #[test]
    fn test_mask_error_invalid_span_display() {
        let err = MaskError::InvalidSpan {
            start: 5,
            end: 50,
            text_len: 10,
        };
        let msg = err.to_string();
        assert!(msg.contains("Invalid detection span"));
        assert!(msg.contains("start=5"));
        assert!(msg.contains("end=50"));
        assert!(msg.contains("text_len=10"));
    }

    #[test]
    fn test_mask_error_invalid_utf8_boundary_display() {
        let err = MaskError::InvalidUtf8Boundary { start: 1, end: 2 };
        let msg = err.to_string();
        assert!(msg.contains("Invalid UTF-8 boundary"));
        assert!(msg.contains("start=1"));
        assert!(msg.contains("end=2"));
    }

    #[test]
    fn test_pattern_error_regex_compile_display() {
        let invalid = String::from("[[[");
        let source = regex::Regex::new(&invalid).expect_err("invalid regex");
        let err = PatternError::RegexCompile {
            pattern: "[[[".to_string(),
            source,
        };
        let msg = err.to_string();
        assert!(msg.contains("Failed to compile regex pattern"));
        assert!(msg.contains("[[["));
    }

    #[test]
    fn test_pattern_error_regex_set_compile_display() {
        let invalid = String::from("[[[");
        let source = RegexSet::new([invalid.as_str()]).expect_err("invalid regex set");
        let err = PatternError::RegexSetCompile { source };
        let msg = err.to_string();
        assert!(msg.contains("Failed to compile RegexSet"));
    }

    #[test]
    fn test_pattern_error_whitelist_compile_display() {
        let invalid = String::from("[[[");
        let source = regex::Regex::new(&invalid).expect_err("invalid regex");
        let err = PatternError::WhitelistCompile {
            pattern: "[[[".to_string(),
            source,
        };
        let msg = err.to_string();
        assert!(msg.contains("Invalid whitelist pattern"));
        assert!(msg.contains("[[["));
    }

    #[test]
    fn test_config_error_missing_field_display() {
        let err = ConfigError::MissingField { field: "foo" };
        assert_eq!(err.to_string(), "Missing required field 'foo'");
    }

    #[test]
    fn test_config_error_invalid_field_display() {
        let err = ConfigError::InvalidField {
            field: "bar",
            details: "not a bool".to_string(),
        };
        assert!(err.to_string().contains("Invalid value for field 'bar'"));
        assert!(err.to_string().contains("not a bool"));
    }

    #[test]
    fn test_pii_filter_error_from_mask_error() {
        let mask_err = MaskError::InvalidSpan {
            start: 0,
            end: 1,
            text_len: 0,
        };
        let pii_err: PIIFilterError = mask_err.into();
        let msg = pii_err.to_string();
        assert!(msg.contains("Invalid detection span"));
    }

    #[test]
    fn test_block_error_display() {
        let err = BlockError::DetectionBlocked {
            count: 2,
            pii_types: "email, ssn".to_string(),
        };
        let msg = err.to_string();
        assert!(msg.contains("blocked content processing"));
        assert!(msg.contains("2 detection"));
        assert!(msg.contains("email, ssn"));
    }

    #[test]
    fn test_to_py_err_uses_runtime_error_for_block_errors() {
        Python::attach(|py| {
            let err = PIIFilterError::from(BlockError::DetectionBlocked {
                count: 1,
                pii_types: "ssn".to_string(),
            })
            .to_py_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyRuntimeError>(py));
        });
    }
}
