use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use regex::Regex;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

struct CompiledValidator {
    max_param_length: usize,
    dangerous_patterns: Vec<Regex>,
}

static VALIDATOR_CACHE: Lazy<Mutex<HashMap<String, Arc<CompiledValidator>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

fn build_cache_key(max_param_length: usize, dangerous_patterns: &[String]) -> String {
    let mut cache_key = max_param_length.to_string();
    for pattern in dangerous_patterns {
        cache_key.push('\u{1f}');
        cache_key.push_str(pattern);
    }
    cache_key
}

fn get_validator(
    max_param_length: usize,
    dangerous_patterns: &[String],
) -> PyResult<Arc<CompiledValidator>> {
    let cache_key = build_cache_key(max_param_length, dangerous_patterns);

    if let Some(existing) = VALIDATOR_CACHE.lock().unwrap().get(&cache_key).cloned() {
        return Ok(existing);
    }

    let compiled_patterns = dangerous_patterns
        .iter()
        .map(|pattern| {
            Regex::new(pattern)
                .map_err(|error| PyErr::new::<pyo3::exceptions::PyValueError, _>(error.to_string()))
        })
        .collect::<PyResult<Vec<_>>>()?;

    let validator = Arc::new(CompiledValidator {
        max_param_length,
        dangerous_patterns: compiled_patterns,
    });

    VALIDATOR_CACHE
        .lock()
        .unwrap()
        .insert(cache_key, validator.clone());
    Ok(validator)
}

fn validate_string(
    key: &str,
    value: &str,
    validator: &CompiledValidator,
) -> Option<(String, String)> {
    if value.len() > validator.max_param_length {
        return Some((key.to_owned(), "max_length".to_owned()));
    }

    for pattern in &validator.dangerous_patterns {
        if pattern.is_match(value) {
            return Some((key.to_owned(), "dangerous_pattern".to_owned()));
        }
    }

    None
}

fn walk_json_like(
    data: &Bound<'_, PyAny>,
    validator: &CompiledValidator,
) -> PyResult<Option<(String, String)>> {
    if let Ok(dict) = data.cast::<PyDict>() {
        for (key, value) in dict.iter() {
            if value.is_instance_of::<PyString>() {
                let key_string = key.str()?.to_string_lossy().into_owned();
                let value_string = value.cast::<PyString>()?.to_str()?.to_owned();
                if let Some(result) = validate_string(&key_string, &value_string, validator) {
                    return Ok(Some(result));
                }
            } else if value.is_instance_of::<PyDict>() || value.is_instance_of::<PyList>() {
                if let Some(result) = walk_json_like(&value, validator)? {
                    return Ok(Some(result));
                }
            }
        }
        return Ok(None);
    }

    if let Ok(list) = data.cast::<PyList>() {
        for item in list.iter() {
            if let Some(result) = walk_json_like(&item, validator)? {
                return Ok(Some(result));
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
    let validator = get_validator(max_param_length, &dangerous_patterns)?;
    walk_json_like(data, validator.as_ref())
}

#[pymodule]
fn validation_middleware_sidecar(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(validate_json_data, module)?)?;
    Ok(())
}
