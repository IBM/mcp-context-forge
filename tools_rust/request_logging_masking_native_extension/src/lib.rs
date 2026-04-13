use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes, PyDict, PyList, PyString};
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;
use serde_json::Value;
use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};

const MASKED_VALUE: &str = "******";
const NESTED_TOO_DEEP: &str = "<nested too deep>";
const KEY_CACHE_CAPACITY: usize = 4096;

thread_local! {
    static KEY_SENSITIVITY_CACHE: RefCell<KeySensitivityCache> =
        RefCell::new(KeySensitivityCache::with_capacity(KEY_CACHE_CAPACITY));
}

struct KeySensitivityCache {
    entries: HashMap<String, bool>,
    insertion_order: VecDeque<String>,
    capacity: usize,
}

impl KeySensitivityCache {
    fn with_capacity(capacity: usize) -> Self {
        Self {
            entries: HashMap::with_capacity(capacity),
            insertion_order: VecDeque::with_capacity(capacity),
            capacity,
        }
    }

    fn get_or_compute(&mut self, key: &str) -> bool {
        if let Some(result) = self.entries.get(key).copied() {
            self.touch(key);
            return result;
        }

        let result = is_sensitive_key(key);
        self.insert(key, result);
        result
    }

    fn insert(&mut self, key: &str, value: bool) {
        if self.capacity == 0 {
            return;
        }

        if self.entries.contains_key(key) {
            self.entries.insert(key.to_owned(), value);
            self.touch(key);
            return;
        }

        if self.entries.len() >= self.capacity {
            if let Some(oldest_key) = self.insertion_order.pop_front() {
                self.entries.remove(&oldest_key);
            }
        }

        let owned_key = key.to_owned();
        self.insertion_order.push_back(owned_key.clone());
        self.entries.insert(owned_key, value);
    }

    fn touch(&mut self, key: &str) {
        if let Some(position) = self
            .insertion_order
            .iter()
            .position(|existing| existing == key)
        {
            self.insertion_order.remove(position);
            self.insertion_order.push_back(key.to_owned());
        }
    }
}

fn normalize_key_for_masking(key: &str) -> String {
    let mut normalized = String::with_capacity(key.len() + 4);
    let mut previous_is_lower_or_digit = false;
    let mut previous_was_underscore = false;

    for ch in key.chars() {
        let is_upper = ch.is_ascii_uppercase();
        let is_alnum = ch.is_ascii_alphanumeric();

        if is_upper && previous_is_lower_or_digit && !previous_was_underscore {
            normalized.push('_');
        }

        if is_alnum {
            normalized.push(ch.to_ascii_lowercase());
            previous_was_underscore = false;
        } else if !previous_was_underscore && !normalized.is_empty() {
            normalized.push('_');
            previous_was_underscore = true;
        }

        previous_is_lower_or_digit = ch.is_ascii_lowercase() || ch.is_ascii_digit();
        if is_upper {
            previous_was_underscore = false;
        }
    }

    while normalized.ends_with('_') {
        normalized.pop();
    }

    normalized
}

fn has_non_sensitive_suffix(normalized_key: &str) -> bool {
    [
        "_count", "_counts", "_size", "_length", "_ttl", "_seconds", "_ms", "_id", "_ids", "_name",
        "_type", "_url", "_uri", "_path", "_status", "_code",
    ]
    .iter()
    .any(|suffix| normalized_key.ends_with(suffix))
}

fn is_sensitive_key(key: &str) -> bool {
    let normalized_key = normalize_key_for_masking(key);
    if normalized_key.is_empty() {
        return false;
    }

    let has_suffix = has_non_sensitive_suffix(&normalized_key);

    if matches!(
        normalized_key.as_str(),
        "password"
            | "passphrase"
            | "secret"
            | "token"
            | "api_key"
            | "apikey"
            | "access_token"
            | "refresh_token"
            | "client_secret"
            | "authorization"
            | "auth_token"
            | "jwt_token"
            | "private_key"
    ) {
        return true;
    }

    if !has_suffix
        && normalized_key
            .split('_')
            .any(|token| matches!(token, "auth" | "authorization" | "jwt"))
    {
        return true;
    }

    if has_suffix {
        return false;
    }

    let mut previous = "";
    for token in normalized_key.split('_').filter(|part| !part.is_empty()) {
        if matches!(
            token,
            "password" | "passphrase" | "secret" | "token" | "apikey" | "authorization"
        ) {
            return true;
        }

        if matches!(
            (previous, token),
            ("api", "key")
                | ("access", "token")
                | ("refresh", "token")
                | ("client", "secret")
                | ("auth", "token")
                | ("jwt", "token")
                | ("private", "key")
        ) {
            return true;
        }

        previous = token;
    }

    false
}

fn is_sensitive_key_cached(key: &str, request_cache: &mut HashMap<String, bool>) -> bool {
    if let Some(result) = request_cache.get(key) {
        return *result;
    }

    let result = KEY_SENSITIVITY_CACHE.with(|cache| cache.borrow_mut().get_or_compute(key));
    request_cache.insert(key.to_owned(), result);
    result
}

fn mask_cookie_header(cookie_header: &str) -> String {
    let mut masked = String::with_capacity(cookie_header.len());
    let mut first = true;

    for cookie in cookie_header.split(';') {
        if first {
            first = false;
        } else {
            masked.push_str("; ");
        }

        let trimmed = cookie.trim();
        if let Some((name, _)) = trimmed.split_once('=') {
            let name = name.trim();
            let lowered = name.to_ascii_lowercase();
            if lowered.contains("jwt")
                || lowered.contains("token")
                || lowered.contains("auth")
                || lowered.contains("session")
            {
                masked.push_str(name);
                masked.push('=');
                masked.push_str(MASKED_VALUE);
            } else {
                masked.push_str(trimmed);
            }
        } else {
            masked.push_str(trimmed);
        }
    }

    masked
}

fn mask_sensitive_data_inner(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    max_depth: i32,
    key_cache: &mut HashMap<String, bool>,
) -> PyResult<Py<PyAny>> {
    if max_depth <= 0 {
        return Ok(PyString::new(py, NESTED_TOO_DEEP).into_any().unbind());
    }

    if let Ok(dict) = data.cast::<PyDict>() {
        let masked = PyDict::new(py);
        for (key, value) in dict.iter() {
            let key_string_object = key.str()?;
            let key_string = key_string_object.to_string_lossy();
            if is_sensitive_key_cached(key_string.as_ref(), key_cache) {
                masked.set_item(key, MASKED_VALUE)?;
            } else {
                masked.set_item(
                    key,
                    mask_sensitive_data_inner(py, &value, max_depth - 1, key_cache)?,
                )?;
            }
        }
        return Ok(masked.into_any().unbind());
    }

    if let Ok(list) = data.cast::<PyList>() {
        let masked = PyList::empty(py);
        for item in list.iter() {
            masked.append(mask_sensitive_data_inner(
                py,
                &item,
                max_depth - 1,
                key_cache,
            )?)?;
        }
        return Ok(masked.into_any().unbind());
    }

    Ok(data.clone().unbind())
}

fn mask_json_value_inner(
    value: Value,
    max_depth: i32,
    key_cache: &mut HashMap<String, bool>,
) -> Value {
    if max_depth <= 0 {
        return Value::String(NESTED_TOO_DEEP.to_owned());
    }

    match value {
        Value::Object(source) => {
            let mut masked = serde_json::Map::with_capacity(source.len());
            for (key, value) in source {
                if is_sensitive_key_cached(&key, key_cache) {
                    masked.insert(key, Value::String(MASKED_VALUE.to_owned()));
                } else {
                    masked.insert(key, mask_json_value_inner(value, max_depth - 1, key_cache));
                }
            }
            Value::Object(masked)
        }
        Value::Array(source) => Value::Array(
            source
                .into_iter()
                .map(|item| mask_json_value_inner(item, max_depth - 1, key_cache))
                .collect(),
        ),
        other => other,
    }
}

#[gen_stub_pyfunction]
#[pyfunction]
fn mask_sensitive_data(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    max_depth: Option<i32>,
) -> PyResult<Py<PyAny>> {
    let mut key_cache = HashMap::with_capacity(16);
    mask_sensitive_data_inner(py, data, max_depth.unwrap_or(10), &mut key_cache)
}

#[gen_stub_pyfunction]
#[pyfunction]
fn mask_sensitive_headers(py: Python<'_>, headers: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let source = headers.cast::<PyDict>()?;
    let masked = PyDict::new(py);
    let mut key_cache = HashMap::with_capacity(source.len());

    for (key, value) in source.iter() {
        let key_string_object = key.str()?;
        let key_string = key_string_object.to_string_lossy();
        if is_sensitive_key_cached(key_string.as_ref(), &mut key_cache) {
            masked.set_item(key, MASKED_VALUE)?;
            continue;
        }

        if key_string.as_ref().eq_ignore_ascii_case("cookie") && value.is_instance_of::<PyString>()
        {
            let cookie_value = value.cast::<PyString>()?.to_str()?;
            masked.set_item(key, mask_cookie_header(cookie_value))?;
            continue;
        }

        masked.set_item(key, value)?;
    }

    Ok(masked.into_any().unbind())
}

#[gen_stub_pyfunction]
#[pyfunction]
fn mask_sensitive_json_bytes(
    py: Python<'_>,
    payload: Vec<u8>,
    max_depth: Option<i32>,
) -> PyResult<Py<PyAny>> {
    let parsed: Value =
        serde_json::from_slice(&payload).map_err(|err| PyValueError::new_err(err.to_string()))?;
    let mut key_cache = HashMap::with_capacity(16);
    let masked = mask_json_value_inner(parsed, max_depth.unwrap_or(10), &mut key_cache);
    let serialized =
        serde_json::to_vec(&masked).map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(PyBytes::new(py, &serialized).into_any().unbind())
}

#[pymodule]
fn request_logging_masking_native_extension(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(mask_sensitive_data, module)?)?;
    module.add_function(wrap_pyfunction!(mask_sensitive_headers, module)?)?;
    module.add_function(wrap_pyfunction!(mask_sensitive_json_bytes, module)?)?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);

#[cfg(test)]
mod tests {
    use super::{
        mask_cookie_header, mask_json_value_inner, normalize_key_for_masking, KeySensitivityCache,
    };
    use serde_json::json;
    use std::collections::HashMap;

    #[test]
    fn normalize_key_trims_trailing_separators_without_extra_allocation_artifacts() {
        assert_eq!(
            normalize_key_for_masking("__ClientSecret__"),
            "client_secret"
        );
        assert_eq!(normalize_key_for_masking("auth-token---"), "auth_token");
    }

    #[test]
    fn mask_cookie_header_preserves_spacing_and_masks_sensitive_cookie_names() {
        assert_eq!(
            mask_cookie_header("jwt_token=abc; theme=dark; session_id=xyz"),
            "jwt_token=******; theme=dark; session_id=******"
        );
        assert_eq!(mask_cookie_header("theme=dark"), "theme=dark");
    }

    #[test]
    fn mask_json_value_masks_nested_sensitive_keys() {
        let mut cache = HashMap::new();
        let masked = mask_json_value_inner(
            json!({"password": "secret", "nested": {"authToken": "abc", "count": 3}}),
            10,
            &mut cache,
        );

        assert_eq!(
            masked,
            json!({"password": "******", "nested": {"authToken": "******", "count": 3}}) // pragma: allowlist secret
        );
    }

    #[test]
    fn key_sensitivity_cache_evicts_least_recently_used_entry_when_capacity_is_reached() {
        let mut cache = KeySensitivityCache::with_capacity(2);

        assert!(cache.get_or_compute("password"));
        assert!(cache.get_or_compute("authToken"));
        assert!(cache.get_or_compute("password"));
        assert!(!cache.get_or_compute("safeField"));

        assert!(cache.entries.contains_key("password"));
        assert!(!cache.entries.contains_key("authToken"));
        assert!(cache.entries.contains_key("safeField"));
    }
}
