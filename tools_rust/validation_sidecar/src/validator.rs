// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Parser backends and JSON-tree validation logic for the sidecar.

use crate::protocol::ValidationRequest;
use regex::Regex;
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::HashMap,
    sync::{Arc, LazyLock, Mutex},
};
use thiserror::Error;

pub const MAX_JSON_DEPTH: usize = 1024;
pub const DEFAULT_DANGEROUS_PATTERNS: [&str; 3] =
    [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationRejection {
    pub key: String,
    pub error_type: String,
    pub detail: String,
}

impl ValidationRejection {
    fn new(
        key: impl Into<String>,
        error_type: impl Into<String>,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            key: key.into(),
            error_type: error_type.into(),
            detail: detail.into(),
        }
    }
}

#[derive(Debug, Error)]
pub enum ValidatorError {
    #[error("dangerous pattern regex is not supported by Rust regex: {0}")]
    InvalidRegex(#[from] regex::Error),
    #[error("invalid JSON for selected parser: {0}")]
    Parse(String),
}

#[derive(Debug, Clone)]
struct CompiledValidator {
    max_param_length: usize,
    dangerous_pattern: Option<Regex>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct ValidatorCacheKey {
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
}

#[derive(Debug, Default)]
struct ValidatorCache {
    entries: Mutex<HashMap<ValidatorCacheKey, Arc<CompiledValidator>>>,
}

impl CompiledValidator {
    fn new(max_param_length: usize, dangerous_patterns: &[String]) -> Result<Self, ValidatorError> {
        let dangerous_pattern = if dangerous_patterns.is_empty() {
            None
        } else {
            let combined = dangerous_patterns
                .iter()
                .map(|pattern| format!("(?:{pattern})"))
                .collect::<Vec<_>>()
                .join("|");
            Some(Regex::new(&combined)?)
        };

        Ok(Self {
            max_param_length,
            dangerous_pattern,
        })
    }
}

impl ValidatorCache {
    fn get_or_compile(
        &self,
        max_param_length: usize,
        dangerous_patterns: &[String],
    ) -> Result<Arc<CompiledValidator>, ValidatorError> {
        let key = ValidatorCacheKey {
            max_param_length,
            dangerous_patterns: dangerous_patterns.to_vec(),
        };

        let mut entries = self.entries.lock().expect("validator cache mutex poisoned");
        if let Some(compiled) = entries.get(&key) {
            return Ok(Arc::clone(compiled));
        }

        let compiled = Arc::new(CompiledValidator::new(
            max_param_length,
            &key.dangerous_patterns,
        )?);
        entries.insert(key, Arc::clone(&compiled));
        Ok(compiled)
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.entries
            .lock()
            .expect("validator cache mutex poisoned")
            .len()
    }
}

static VALIDATOR_CACHE: LazyLock<ValidatorCache> = LazyLock::new(ValidatorCache::default);

pub fn validate_request(
    request: &ValidationRequest,
) -> Result<Option<ValidationRejection>, ValidatorError> {
    let validator =
        VALIDATOR_CACHE.get_or_compile(request.max_param_length, &request.dangerous_patterns)?;
    match parse_json(&request.raw_body) {
        Ok(value) => Ok(walk_json(&value, &validator, 0)),
        Err(_) => Ok(Some(ValidationRejection::new(
            "payload",
            "invalid_json",
            "Request body contains invalid JSON",
        ))),
    }
}

fn parse_json(raw_body: &[u8]) -> Result<Value, ValidatorError> {
    let mut deserializer = serde_json::Deserializer::from_slice(raw_body);
    deserializer.disable_recursion_limit();
    let deserializer = serde_stacker::Deserializer::new(&mut deserializer);
    Value::deserialize(deserializer).map_err(|error| ValidatorError::Parse(error.to_string()))
}

fn walk_json(
    value: &Value,
    validator: &CompiledValidator,
    depth: usize,
) -> Option<ValidationRejection> {
    if depth > MAX_JSON_DEPTH {
        return Some(ValidationRejection::new(
            "payload",
            "max_depth",
            "JSON payload exceeds maximum supported nesting depth",
        ));
    }

    match value {
        Value::Object(map) => map.iter().find_map(|(key, value)| match value {
            Value::String(string_value) => validate_string(key, string_value, validator),
            Value::Object(_) | Value::Array(_) => walk_json(value, validator, depth + 1),
            _ => None,
        }),
        Value::Array(items) => items.iter().find_map(|item| match item {
            Value::String(string_value) => validate_string("list_item", string_value, validator),
            Value::Object(_) | Value::Array(_) => walk_json(item, validator, depth + 1),
            _ => None,
        }),
        _ => None,
    }
}

fn validate_string(
    key: &str,
    value: &str,
    validator: &CompiledValidator,
) -> Option<ValidationRejection> {
    if value.chars().count() > validator.max_param_length {
        return Some(ValidationRejection::new(
            key,
            "max_length",
            format!("Parameter {key} exceeds maximum length"),
        ));
    }

    if validator
        .dangerous_pattern
        .as_ref()
        .is_some_and(|pattern| pattern.is_match(value))
    {
        return Some(ValidationRejection::new(
            key,
            "dangerous_pattern",
            format!("Parameter {key} contains dangerous characters"),
        ));
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::ValidationRequest;

    fn default_patterns() -> Vec<String> {
        DEFAULT_DANGEROUS_PATTERNS
            .iter()
            .map(ToString::to_string)
            .collect()
    }

    fn request(body: &str, max_param_length: usize, patterns: &[String]) -> ValidationRequest {
        ValidationRequest::from_raw_body(body.as_bytes(), max_param_length, patterns)
            .expect("request")
    }

    #[test]
    fn serde_json_backend_rejects_dangerous_strings() {
        let rejection =
            validate_request(&request(r#"{"name":"<script>"}"#, 64, &default_patterns()))
                .expect("validation")
                .expect("rejection");

        assert_eq!(rejection.key, "name");
        assert_eq!(rejection.error_type, "dangerous_pattern");
    }

    #[test]
    fn unicode_length_uses_character_count_not_utf8_bytes() {
        let result = validate_request(&request(r#"{"name":"é"}"#, 1, &default_patterns()))
            .expect("validation");
        assert!(result.is_none());
    }

    #[test]
    fn list_item_strings_are_validated() {
        let rejection =
            validate_request(&request(r#"["safe","<script>"]"#, 64, &default_patterns()))
                .expect("validation")
                .expect("rejection");

        assert_eq!(rejection.key, "list_item");
        assert_eq!(rejection.error_type, "dangerous_pattern");
    }

    #[test]
    fn default_dangerous_patterns_match_python_defaults() {
        let rejection =
            validate_request(&request(r#"{"path":"../secret"}"#, 64, &default_patterns()))
                .expect("validation")
                .expect("rejection");

        assert_eq!(rejection.key, "path");
        assert_eq!(rejection.error_type, "dangerous_pattern");
    }

    #[test]
    fn non_string_scalars_are_ignored() {
        let result = validate_request(&request(
            r#"{"count":123,"enabled":true,"value":null}"#,
            1,
            &default_patterns(),
        ))
        .expect("validation");

        assert!(result.is_none());
    }

    #[test]
    fn max_depth_is_enforced() {
        let mut payload = "{}".to_owned();
        for _ in 0..=MAX_JSON_DEPTH {
            payload = format!(r#"{{"nested":{payload}}}"#);
        }

        let rejection = validate_request(&request(&payload, 64, &default_patterns()))
            .expect("validation")
            .expect("rejection");

        assert_eq!(rejection.error_type, "max_depth");
    }

    #[test]
    fn invalid_json_is_a_validation_verdict() {
        let rejection = validate_request(&request("{not-json", 64, &default_patterns()))
            .expect("validation")
            .expect("rejection");

        assert_eq!(rejection.error_type, "invalid_json");
    }

    #[test]
    fn compiled_validators_are_reused_for_identical_settings() {
        let cache = ValidatorCache::default();
        let patterns = default_patterns();

        let first = cache
            .get_or_compile(64, &patterns)
            .expect("first validator");
        let second = cache
            .get_or_compile(64, &patterns)
            .expect("second validator");

        assert!(Arc::ptr_eq(&first, &second));
        assert_eq!(cache.len(), 1);
    }
}
