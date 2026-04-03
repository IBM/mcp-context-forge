use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use regex::Regex;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

const MAX_JSON_DEPTH: usize = 1024;

struct CompiledValidator {
    max_param_length: usize,
    dangerous_pattern: Option<Regex>,
}

#[derive(Clone, Eq, Hash, PartialEq)]
struct CacheKey {
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
}

enum ValidationFailure {
    MaxLength,
    DangerousPattern,
}

static VALIDATOR_CACHE: Lazy<Mutex<HashMap<CacheKey, Arc<CompiledValidator>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

fn get_validator(
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
) -> PyResult<Arc<CompiledValidator>> {
    let cache_key = CacheKey {
        max_param_length,
        dangerous_patterns,
    };

    let mut cache = VALIDATOR_CACHE.lock().unwrap();
    if let Some(existing) = cache.get(&cache_key).cloned() {
        return Ok(existing);
    }

    let combined_pattern =
        if cache_key.dangerous_patterns.is_empty() {
            None
        } else {
            let joined = cache_key
                .dangerous_patterns
                .iter()
                .map(|pattern| format!("(?:{pattern})"))
                .collect::<Vec<_>>()
                .join("|");
            Some(Regex::new(&joined).map_err(|error| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(error.to_string())
            })?)
        };

    let validator = Arc::new(CompiledValidator {
        max_param_length,
        dangerous_pattern: combined_pattern,
    });

    cache.insert(cache_key, validator.clone());
    Ok(validator)
}

fn validate_string(value: &str, validator: &CompiledValidator) -> Option<ValidationFailure> {
    if value.chars().count() > validator.max_param_length {
        return Some(ValidationFailure::MaxLength);
    }

    if validator
        .dangerous_pattern
        .as_ref()
        .is_some_and(|pattern| pattern.is_match(value))
    {
        return Some(ValidationFailure::DangerousPattern);
    }

    None
}

fn walk_json_like(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    validator: &CompiledValidator,
) -> PyResult<Option<(String, String)>> {
    let mut stack = vec![(data.clone().unbind(), 0usize)];

    while let Some((item, depth)) = stack.pop() {
        if depth > MAX_JSON_DEPTH {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "JSON payload exceeds maximum supported nesting depth",
            ));
        }

        let bound_item = item.bind(py);

        if let Ok(dict) = bound_item.cast::<PyDict>() {
            for (key, value) in dict.iter() {
                if let Ok(value_string) = value.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        let key_string = key.str()?.to_string_lossy().into_owned();
                        let error_type = match result {
                            ValidationFailure::MaxLength => "max_length",
                            ValidationFailure::DangerousPattern => "dangerous_pattern",
                        };
                        return Ok(Some((key_string, error_type.to_owned())));
                    }
                } else if value.is_instance_of::<PyDict>() || value.is_instance_of::<PyList>() {
                    stack.push((value.unbind(), depth + 1));
                }
            }
            continue;
        }

        if let Ok(list) = bound_item.cast::<PyList>() {
            for child in list.iter().rev() {
                if child.is_instance_of::<PyDict>() || child.is_instance_of::<PyList>() {
                    stack.push((child.unbind(), depth + 1));
                } else if let Ok(value_string) = child.cast::<PyString>() {
                    if let Some(result) = validate_string(value_string.to_str()?, validator) {
                        let error_type = match result {
                            ValidationFailure::MaxLength => "max_length",
                            ValidationFailure::DangerousPattern => "dangerous_pattern",
                        };
                        return Ok(Some(("list_item".to_owned(), error_type.to_owned())));
                    }
                }
            }
        }
    }

    Ok(None)
}

#[pyfunction]
fn validate_json_data(
    data: &Bound<'_, PyAny>,
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
) -> PyResult<Option<(String, String)>> {
    let validator = get_validator(max_param_length, dangerous_patterns)?;
    walk_json_like(data.py(), data, validator.as_ref())
}

#[pymodule]
fn validation_middleware_sidecar(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(validate_json_data, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::{PyDict, PyList};

    #[test]
    fn validate_string_uses_character_count_not_utf8_bytes() {
        let validator = CompiledValidator {
            max_param_length: 1,
            dangerous_pattern: None,
        };

        assert!(validate_string("é", &validator).is_none());
    }

    #[test]
    fn walk_json_like_handles_deeply_nested_payloads() {
        Python::initialize();
        Python::attach(|py| {
            let validator = CompiledValidator {
                max_param_length: 32,
                dangerous_pattern: Some(Regex::new("<script").unwrap()),
            };

            let mut payload = PyDict::new(py).unbind();
            payload.bind(py).set_item("value", "safe").unwrap();

            for _ in 0..20_000 {
                let wrapper = PyDict::new(py);
                wrapper.set_item("nested", payload.bind(py)).unwrap();
                payload = wrapper.unbind();
            }

            let err = walk_json_like(py, payload.bind(py).as_any(), &validator).unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));

            let failing_payload = PyDict::new(py);
            let values = PyList::empty(py);
            let nested = PyDict::new(py);
            nested.set_item("name", "<script>").unwrap();
            values.append(nested).unwrap();
            failing_payload.set_item("items", values).unwrap();

            let result = walk_json_like(py, failing_payload.as_any(), &validator).unwrap();
            assert_eq!(result, Some(("name".to_owned(), "dangerous_pattern".to_owned())));
        });
    }

    #[test]
    fn walk_json_like_rejects_dangerous_string_items_in_lists() {
        Python::initialize();
        Python::attach(|py| {
            let validator = CompiledValidator {
                max_param_length: 32,
                dangerous_pattern: Some(Regex::new("<script").unwrap()),
            };

            let payload = PyList::empty(py);
            payload.append("<script>").unwrap();

            let result = walk_json_like(py, payload.as_any(), &validator).unwrap();
            assert_eq!(result, Some(("list_item".to_owned(), "dangerous_pattern".to_owned())));
        });
    }
}
