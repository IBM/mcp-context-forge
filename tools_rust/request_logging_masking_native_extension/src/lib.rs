use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use std::collections::HashMap;

const MASKED_VALUE: &str = "******";
const NESTED_TOO_DEEP: &str = "<nested too deep>";

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

    normalized.trim_matches('_').to_owned()
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

fn is_sensitive_key_cached(key: &str, cache: &mut HashMap<String, bool>) -> bool {
    if let Some(result) = cache.get(key) {
        return *result;
    }

    let result = is_sensitive_key(key);
    cache.insert(key.to_owned(), result);
    result
}

fn mask_cookie_header(cookie_header: &str) -> String {
    let mut masked = Vec::new();

    for cookie in cookie_header.split(';') {
        let trimmed = cookie.trim();
        if let Some((name, _)) = trimmed.split_once('=') {
            let name = name.trim();
            let lowered = name.to_ascii_lowercase();
            if lowered.contains("jwt")
                || lowered.contains("token")
                || lowered.contains("auth")
                || lowered.contains("session")
            {
                masked.push(format!("{name}={MASKED_VALUE}"));
            } else {
                masked.push(trimmed.to_owned());
            }
        } else {
            masked.push(trimmed.to_owned());
        }
    }

    masked.join("; ")
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
            let key_string = key.str()?.to_string_lossy().into_owned();
            if is_sensitive_key_cached(&key_string, key_cache) {
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

#[pyfunction]
fn mask_sensitive_data(
    py: Python<'_>,
    data: &Bound<'_, PyAny>,
    max_depth: Option<i32>,
) -> PyResult<Py<PyAny>> {
    let mut key_cache = HashMap::new();
    mask_sensitive_data_inner(py, data, max_depth.unwrap_or(10), &mut key_cache)
}

#[pyfunction]
fn mask_sensitive_headers(py: Python<'_>, headers: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let source = headers.cast::<PyDict>()?;
    let masked = PyDict::new(py);
    let mut key_cache = HashMap::with_capacity(source.len());

    for (key, value) in source.iter() {
        let key_string = key.str()?.to_string_lossy().into_owned();
        if is_sensitive_key_cached(&key_string, &mut key_cache) {
            masked.set_item(key, MASKED_VALUE)?;
            continue;
        }

        if key_string.eq_ignore_ascii_case("cookie") && value.is_instance_of::<PyString>() {
            let cookie_value = value.cast::<PyString>()?.to_str()?;
            masked.set_item(key, mask_cookie_header(cookie_value))?;
            continue;
        }

        masked.set_item(key, value)?;
    }

    Ok(masked.into_any().unbind())
}

#[pymodule]
fn request_logging_masking_native_extension(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(mask_sensitive_data, module)?)?;
    module.add_function(wrap_pyfunction!(mask_sensitive_headers, module)?)?;
    Ok(())
}
