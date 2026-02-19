mod config;
mod patterns;
mod scanner;

use std::fmt;

use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;

pub use config::SecretsDetectionConfig;
pub use patterns::PATTERNS;
pub use scanner::{detect_and_redact, scan_container};

/// Scan Python container for secrets using optimized type dispatch
///
#[gen_stub_pyfunction]
#[pyfunction]
fn py_scan_container<'py>(
    py: Python<'py>,
    container: Bound<'py, PyAny>,
    config: Bound<'py, PyAny>,
) -> PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> {
    // Extract config from Pydantic model (only once)
    let cfg = SecretsDetectionConfig::try_from(&config)?;

    // Fast path: check type once and dispatch
    let (count, redacted, findings) = if container.is_instance_of::<PyString>() {
        // String: direct extraction (fastest path)
        let text = container.extract::<String>()?;
        let (fs, redacted_str) = detect_and_redact(&text, &cfg);

        let findings_list = PyList::empty(py);
        for finding in &fs {
            let finding_dict = PyDict::new(py);
            finding_dict.set_item("type", &finding.pii_type)?;
            finding_dict.set_item("match", &finding.preview)?;
            findings_list.append(finding_dict)?;
        }

        (
            fs.len(),
            PyString::new(py, &redacted_str).into_any(),
            findings_list,
        )
    } else if container.is_instance_of::<PyDict>() {
        // Dict: use specialized scanner
        scan_container(py, &container, &cfg)?
    } else if container.is_instance_of::<PyList>() {
        // List: use specialized scanner
        scan_container(py, &container, &cfg)?
    } else {
        // Other types: no processing
        let findings = PyList::empty(py);
        (0, container.clone(), findings)
    };

    Ok((count, redacted, findings))
}

#[pymodule]
fn secrets_detection_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_scan_container, m)?)?;
    Ok(())
}

// Define stub info gatherer for generating Python type stubs
define_stub_info_gatherer!(stub_info);

/// Helper function to extract and convert Python attributes with custom error type
fn extract_attr<'py, T>(
    obj: &Bound<'py, PyAny>,
    attr_name: &str,
    expected_type: &str,
) -> PyResult<T>
where
    T: for<'a> FromPyObject<'a, 'a>,
{
    obj.getattr(attr_name)
        .map_err(|_| -> PyErr {
            AttributeError::Missing {
                attr_name: attr_name.to_string(),
            }
            .into()
        })
        .and_then(|attr| {
            attr.extract().map_err(|_| -> PyErr {
                AttributeError::InvalidType {
                    attr_name: attr_name.to_string(),
                    expected_type: expected_type.to_string(),
                }
                .into()
            })
        })
}

/// TryFrom implementation for extracting SecretsDetectionConfig from Python objects
impl<'py> TryFrom<&Bound<'py, PyAny>> for SecretsDetectionConfig {
    type Error = PyErr;

    fn try_from(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        // Extract required attributes from Pydantic model using helper function
        let enabled = extract_attr(obj, "enabled", "Dict[str, bool]")?;
        let redact = extract_attr(obj, "redact", "bool")?;
        let redaction_text = extract_attr(obj, "redaction_text", "str")?;
        let block_on_detection = extract_attr(obj, "block_on_detection", "bool")?;
        let min_findings_to_block = extract_attr(obj, "min_findings_to_block", "int")?;

        Ok(SecretsDetectionConfig {
            enabled,
            redact,
            redaction_text,
            block_on_detection,
            min_findings_to_block,
        })
    }
}

/// Custom error type for attribute extraction
#[derive(Debug)]
enum AttributeError {
    Missing {
        attr_name: String,
    },
    InvalidType {
        attr_name: String,
        expected_type: String,
    },
}

impl fmt::Display for AttributeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AttributeError::Missing { attr_name } => {
                write!(f, "Missing required attribute '{}'", attr_name)
            }
            AttributeError::InvalidType {
                attr_name,
                expected_type,
            } => {
                write!(
                    f,
                    "Invalid type for '{}', expected {}",
                    attr_name, expected_type
                )
            }
        }
    }
}

impl std::error::Error for AttributeError {}

impl From<AttributeError> for PyErr {
    fn from(err: AttributeError) -> PyErr {
        PyAttributeError::new_err(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_attribute_error_missing_display() {
        let err = AttributeError::Missing {
            attr_name: "test_attr".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Missing required attribute 'test_attr'");
    }

    #[test]
    fn test_attribute_error_invalid_type_display() {
        let err = AttributeError::InvalidType {
            attr_name: "test_attr".to_string(),
            expected_type: "str".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Invalid type for 'test_attr', expected str");
    }

    #[test]
    fn test_attribute_error_missing_debug() {
        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        let debug = format!("{:?}", err);
        assert!(debug.contains("Missing"));
        assert!(debug.contains("test"));
    }

    #[test]
    fn test_attribute_error_invalid_type_debug() {
        let err = AttributeError::InvalidType {
            attr_name: "field".to_string(),
            expected_type: "bool".to_string(),
        };
        let debug = format!("{:?}", err);
        assert!(debug.contains("InvalidType"));
        assert!(debug.contains("field"));
        assert!(debug.contains("bool"));
    }

    #[test]
    fn test_attribute_error_is_error_trait() {
        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        // Verify it implements std::error::Error
        let _: &dyn std::error::Error = &err;
    }

    #[test]
    fn test_attribute_error_display_with_special_chars() {
        let err = AttributeError::Missing {
            attr_name: "test_attr_123".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Missing required attribute 'test_attr_123'");
    }

    #[test]
    fn test_attribute_error_display_with_complex_type() {
        let err = AttributeError::InvalidType {
            attr_name: "config".to_string(),
            expected_type: "Dict[str, bool]".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(
            display,
            "Invalid type for 'config', expected Dict[str, bool]"
        );
    }

    #[test]
    fn test_attribute_error_conversion_exists() {
        fn _assert_conversion<T: Into<PyErr>>(_: T) {}

        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        _assert_conversion(err);
    }
}
