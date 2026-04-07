use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use regex::Regex;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::fmt;
use std::path::{Component, Path, PathBuf};

const MAX_JSON_DEPTH: usize = 1024;

#[pyclass(name = "Validator")]
struct CompiledValidator {
    max_param_length: usize,
    matcher: DangerousPatternMatcher,
    allowed_roots: Vec<PathBuf>,
    max_path_depth: usize,
}

struct DangerousPatternMatcher {
    shell_metacharacters: bool,
    path_traversal: bool,
    control_characters: bool,
    fallback_pattern: Option<Regex>,
}

impl DangerousPatternMatcher {
    fn from_patterns(patterns: &[String]) -> PyResult<Self> {
        let mut shell_metacharacters = false;
        let mut path_traversal = false;
        let mut control_characters = false;
        let mut fallback_patterns = Vec::new();

        for pattern in patterns {
            match pattern.as_str() {
                r"[;&|`$(){}\[\]<>]" => shell_metacharacters = true,
                r"\.\.[\\/]" => path_traversal = true,
                r"[\x00-\x1f\x7f-\x9f]" => control_characters = true,
                _ => fallback_patterns.push(pattern.as_str()),
            }
        }

        let fallback_pattern = if fallback_patterns.is_empty() {
            None
        } else {
            let joined = fallback_patterns
                .iter()
                .map(|pattern| format!("(?:{pattern})"))
                .collect::<Vec<_>>()
                .join("|");
            Some(Regex::new(&joined).map_err(|error| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(error.to_string())
            })?)
        };

        Ok(Self {
            shell_metacharacters,
            path_traversal,
            control_characters,
            fallback_pattern,
        })
    }

    fn is_match(&self, value: &str) -> bool {
        if value.is_ascii() {
            let bytes = value.as_bytes();
            if self.shell_metacharacters
                && bytes.iter().any(|byte| {
                    matches!(
                        byte,
                        b';' | b'&'
                            | b'|'
                            | b'`'
                            | b'$'
                            | b'('
                            | b')'
                            | b'{'
                            | b'}'
                            | b'['
                            | b']'
                            | b'<'
                            | b'>'
                    )
                })
            {
                return true;
            }
            if self.path_traversal
                && bytes
                    .windows(3)
                    .any(|window| window == b"../" || window == b"..\\")
            {
                return true;
            }
            if self.control_characters
                && bytes
                    .iter()
                    .any(|byte| matches!(byte, 0x00..=0x1f | 0x7f..=0x9f))
            {
                return true;
            }
        } else {
            if self.path_traversal {
                let mut chars = value.chars();
                let mut first = chars.next();
                let mut second = chars.next();
                for third in chars {
                    if first == Some('.') && second == Some('.') && matches!(third, '/' | '\\') {
                        return true;
                    }
                    first = second;
                    second = Some(third);
                }
            }

            for ch in value.chars() {
                if self.shell_metacharacters
                    && matches!(
                        ch,
                        ';' | '&' | '|' | '`' | '$' | '(' | ')' | '{' | '}' | '[' | ']' | '<' | '>'
                    )
                {
                    return true;
                }
                if self.control_characters {
                    let code = ch as u32;
                    if matches!(code, 0x00..=0x1f | 0x7f..=0x9f) {
                        return true;
                    }
                }
            }
        }

        self.fallback_pattern
            .as_ref()
            .is_some_and(|pattern| pattern.is_match(value))
    }
}

enum ValidationFailure {
    MaxLength,
    DangerousPattern,
}

fn compile_validator(
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
    allowed_roots: Vec<String>,
    max_path_depth: usize,
) -> PyResult<CompiledValidator> {
    let matcher = DangerousPatternMatcher::from_patterns(&dangerous_patterns)?;

    Ok(CompiledValidator {
        max_param_length,
        matcher,
        allowed_roots: allowed_roots.into_iter().map(PathBuf::from).collect(),
        max_path_depth,
    })
}

fn validate_string(value: &str, validator: &CompiledValidator) -> Option<ValidationFailure> {
    if value.is_ascii() {
        if value.len() > validator.max_param_length {
            return Some(ValidationFailure::MaxLength);
        }
    } else if value.chars().count() > validator.max_param_length {
        return Some(ValidationFailure::MaxLength);
    }

    if validator.matcher.is_match(value) {
        return Some(ValidationFailure::DangerousPattern);
    }

    None
}

enum StreamStop {
    Failure(String, String),
    MaxDepth,
    InvalidJson(String),
}

const FAILURE_PREFIX: &str = "__validation_failure__:";
const DEPTH_PREFIX: &str = "__validation_depth__";

fn stream_stop_error<E>(stop: StreamStop) -> E
where
    E: de::Error,
{
    match stop {
        StreamStop::Failure(key, error_type) => {
            E::custom(format!("{FAILURE_PREFIX}{key}:{error_type}"))
        }
        StreamStop::MaxDepth => E::custom(DEPTH_PREFIX),
        StreamStop::InvalidJson(message) => E::custom(message),
    }
}

fn parse_stream_stop(error: serde_json::Error) -> StreamStop {
    let message = error.to_string();
    if let Some(rest) = message.strip_prefix(FAILURE_PREFIX) {
        if let Some((key, error_type)) = rest.rsplit_once(':') {
            let normalized_error_type = error_type
                .split(" at line ")
                .next()
                .unwrap_or(error_type)
                .to_owned();
            return StreamStop::Failure(key.to_owned(), normalized_error_type);
        }
    }
    if message.starts_with(DEPTH_PREFIX) {
        return StreamStop::MaxDepth;
    }
    StreamStop::InvalidJson(message)
}

struct ValueSeed<'a> {
    validator: &'a CompiledValidator,
    depth: usize,
    key_context: Option<&'a str>,
    list_item_context: bool,
}

struct ValueVisitor<'a> {
    seed: ValueSeed<'a>,
}

impl<'de, 'a> DeserializeSeed<'de> for ValueSeed<'a> {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: de::Deserializer<'de>,
    {
        if self.depth > MAX_JSON_DEPTH {
            return Err(stream_stop_error(StreamStop::MaxDepth));
        }

        deserializer.deserialize_any(ValueVisitor { seed: self })
    }
}

impl<'de, 'a> Visitor<'de> for ValueVisitor<'a> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        if let Some(result) = validate_string(value, self.seed.validator) {
            let key = if self.seed.list_item_context {
                "list_item".to_owned()
            } else {
                self.seed.key_context.unwrap_or("payload").to_owned()
            };
            let error_type = match result {
                ValidationFailure::MaxLength => "max_length".to_owned(),
                ValidationFailure::DangerousPattern => "dangerous_pattern".to_owned(),
            };
            return Err(stream_stop_error(StreamStop::Failure(key, error_type)));
        }

        Ok(())
    }

    fn visit_borrowed_str<E>(self, value: &'de str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        self.visit_str(value)
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        self.visit_str(&value)
    }

    fn visit_seq<A>(self, mut seq: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let child_seed = ValueSeed {
            validator: self.seed.validator,
            depth: self.seed.depth + 1,
            key_context: None,
            list_item_context: true,
        };

        while seq.next_element_seed(child_seed.reborrow())?.is_some() {}
        Ok(())
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        while let Some(key) = map.next_key::<String>()? {
            map.next_value_seed(ValueSeed {
                validator: self.seed.validator,
                depth: self.seed.depth + 1,
                key_context: Some(key.as_str()),
                list_item_context: false,
            })?;
        }
        Ok(())
    }
}

impl<'a> ValueSeed<'a> {
    fn reborrow<'b>(&'b self) -> ValueSeed<'b> {
        ValueSeed {
            validator: self.validator,
            depth: self.depth,
            key_context: self.key_context,
            list_item_context: self.list_item_context,
        }
    }
}

fn validate_json_bytes_streaming(
    raw_body: &[u8],
    validator: &CompiledValidator,
) -> PyResult<Option<(String, String)>> {
    let mut deserializer = serde_json::Deserializer::from_slice(raw_body);
    deserializer.disable_recursion_limit();
    let deserializer = serde_stacker::Deserializer::new(&mut deserializer);

    match (ValueSeed {
        validator,
        depth: 0,
        key_context: None,
        list_item_context: false,
    })
    .deserialize(deserializer)
    {
        Ok(()) => Ok(None),
        Err(error) => match parse_stream_stop(error) {
            StreamStop::Failure(key, error_type) => Ok(Some((key, error_type))),
            StreamStop::MaxDepth => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "JSON payload exceeds maximum supported nesting depth",
            )),
            StreamStop::InvalidJson(message) => {
                Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Request body contains invalid JSON: {message}"
                )))
            }
        },
    }
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

fn sanitize_response_body_bytes(body: &[u8]) -> Vec<u8> {
    String::from_utf8_lossy(body)
        .chars()
        .filter(|ch| {
            let code = *ch as u32;
            !(matches!(code, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f..=0x9f))
        })
        .collect::<String>()
        .into_bytes()
}

fn has_uri_scheme(path: &str) -> bool {
    let Some((scheme, _rest)) = path.split_once("://") else {
        return false;
    };
    let mut chars = scheme.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_alphabetic() {
        return false;
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '+' | '-' | '.'))
}

fn normalize_path(path: &str) -> Result<PathBuf, std::io::Error> {
    let candidate = Path::new(path);
    let absolute = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        std::env::current_dir()?.join(candidate)
    };

    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::Prefix(prefix) => normalized.push(prefix.as_os_str()),
            Component::RootDir => normalized.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(part) => normalized.push(part),
        }
    }

    Ok(normalized)
}

fn validate_resource_path_impl(path: &str, validator: &CompiledValidator) -> PyResult<String> {
    if has_uri_scheme(path) {
        return Ok(path.to_owned());
    }

    if path.contains("..") || path.contains("//") {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path traversal detected",
        ));
    }

    let resolved_path = normalize_path(path).map_err(|_| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>("invalid_path: Invalid path")
    })?;

    if resolved_path.components().count() > validator.max_path_depth {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path too deep",
        ));
    }

    if !validator.allowed_roots.is_empty()
        && !validator
            .allowed_roots
            .iter()
            .any(|root| resolved_path.starts_with(root))
    {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "invalid_path: Path outside allowed roots",
        ));
    }

    Ok(resolved_path.to_string_lossy().into_owned())
}

#[pymethods]
impl CompiledValidator {
    #[new]
    #[pyo3(signature = (max_param_length, dangerous_patterns, allowed_roots=Vec::new(), max_path_depth=1024))]
    fn new(
        max_param_length: usize,
        dangerous_patterns: Vec<String>,
        allowed_roots: Vec<String>,
        max_path_depth: usize,
    ) -> PyResult<Self> {
        compile_validator(
            max_param_length,
            dangerous_patterns,
            allowed_roots,
            max_path_depth,
        )
    }

    fn validate_json_data(&self, data: &Bound<'_, PyAny>) -> PyResult<Option<(String, String)>> {
        walk_json_like(data.py(), data, self)
    }

    fn validate_json_bytes(&self, raw_body: &[u8]) -> PyResult<Option<(String, String)>> {
        validate_json_bytes_streaming(raw_body, self)
    }

    #[pyo3(signature = (parameters, content_type, raw_body=None))]
    fn validate_http_request(
        &self,
        parameters: Vec<(String, String)>,
        content_type: &str,
        raw_body: Option<&[u8]>,
    ) -> PyResult<Option<(String, String)>> {
        if let Some(result) = self.validate_parameters(parameters) {
            return Ok(Some(result));
        }

        if content_type.starts_with("application/json") {
            if let Some(body) = raw_body {
                if !body.is_empty() {
                    return self.validate_json_bytes(body);
                }
            }
        }

        Ok(None)
    }

    #[pyo3(signature = (parameters, raw_body=None))]
    fn validate_request_parts(
        &self,
        parameters: Vec<(String, String)>,
        raw_body: Option<&[u8]>,
    ) -> PyResult<Option<(String, String)>> {
        if let Some(result) = self.validate_parameters(parameters) {
            return Ok(Some(result));
        }

        if let Some(body) = raw_body {
            return self.validate_json_bytes(body);
        }

        Ok(None)
    }

    fn validate_parameters(&self, parameters: Vec<(String, String)>) -> Option<(String, String)> {
        parameters.into_iter().find_map(|(key, value)| {
            validate_string(&value, self).map(|failure| match failure {
                ValidationFailure::MaxLength => (key, "max_length".to_owned()),
                ValidationFailure::DangerousPattern => (key, "dangerous_pattern".to_owned()),
            })
        })
    }

    fn validate_resource_path(&self, path: &str) -> PyResult<String> {
        validate_resource_path_impl(path, self)
    }

    fn sanitize_response_body(&self, body: &[u8]) -> Vec<u8> {
        sanitize_response_body_bytes(body)
    }
}

#[pyfunction]
fn validate_json_data(
    data: &Bound<'_, PyAny>,
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
) -> PyResult<Option<(String, String)>> {
    let validator = compile_validator(max_param_length, dangerous_patterns, Vec::new(), 1024)?;
    walk_json_like(data.py(), data, &validator)
}

#[pymodule]
fn validation_middleware_rust(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<CompiledValidator>()?;
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
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
        };

        assert!(validate_string("é", &validator).is_none());
    }

    #[test]
    fn walk_json_like_handles_deeply_nested_payloads() {
        Python::initialize();
        Python::attach(|py| {
            let validator = CompiledValidator {
                max_param_length: 32,
                matcher: DangerousPatternMatcher {
                    shell_metacharacters: false,
                    path_traversal: false,
                    control_characters: false,
                    fallback_pattern: Some(Regex::new("<script").unwrap()),
                },
                allowed_roots: Vec::new(),
                max_path_depth: 1024,
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
            assert_eq!(
                result,
                Some(("name".to_owned(), "dangerous_pattern".to_owned()))
            );
        });
    }

    #[test]
    fn walk_json_like_rejects_dangerous_string_items_in_lists() {
        Python::initialize();
        Python::attach(|py| {
            let validator = CompiledValidator {
                max_param_length: 32,
                matcher: DangerousPatternMatcher {
                    shell_metacharacters: false,
                    path_traversal: false,
                    control_characters: false,
                    fallback_pattern: Some(Regex::new("<script").unwrap()),
                },
                allowed_roots: Vec::new(),
                max_path_depth: 1024,
            };

            let payload = PyList::empty(py);
            payload.append("<script>").unwrap();

            let result = walk_json_like(py, payload.as_any(), &validator).unwrap();
            assert_eq!(
                result,
                Some(("list_item".to_owned(), "dangerous_pattern".to_owned()))
            );
        });
    }

    #[test]
    fn validate_json_bytes_rejects_dangerous_strings() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: Some(Regex::new("<script").unwrap()),
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
        };

        let result = validator
            .validate_json_bytes(br#"{"name":"<script>"}"#)
            .unwrap();
        assert_eq!(
            result,
            Some(("name".to_owned(), "dangerous_pattern".to_owned()))
        );
    }

    #[test]
    fn validate_json_bytes_uses_character_count_not_utf8_bytes() {
        let validator = CompiledValidator {
            max_param_length: 1,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
        };

        let result = validator
            .validate_json_bytes(b"{\"name\":\"\xC3\xA9\"}")
            .unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn validate_parameters_rejects_dangerous_values() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: Some(Regex::new("<script").unwrap()),
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
        };

        let result = validator.validate_parameters(vec![
            ("safe".to_owned(), "ok".to_owned()),
            ("bad".to_owned(), "<script>".to_owned()),
        ]);

        assert_eq!(
            result,
            Some(("bad".to_owned(), "dangerous_pattern".to_owned()))
        );
    }

    #[test]
    fn validate_resource_path_accepts_configured_roots() {
        let tempdir = tempfile::tempdir().unwrap();
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: vec![tempdir.path().to_path_buf()],
            max_path_depth: 1024,
        };

        let candidate = tempdir.path().join("file.txt");
        let result = validate_resource_path_impl(candidate.to_str().unwrap(), &validator).unwrap();

        assert!(result.starts_with(tempdir.path().to_str().unwrap()));
    }

    #[test]
    fn sanitize_response_body_removes_control_characters() {
        let sanitized = sanitize_response_body_bytes(b"Hello\x00World\x1f");
        assert_eq!(sanitized, b"HelloWorld");
    }

    #[test]
    fn validate_request_checks_parameters_before_json_body() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: Some(Regex::new("<script").unwrap()),
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
        };

        let result = validator
            .validate_request_parts(
                vec![("query".to_owned(), "<script>".to_owned())],
                Some(br#"{"name":"safe"}"#),
            )
            .unwrap();

        assert_eq!(
            result,
            Some(("query".to_owned(), "dangerous_pattern".to_owned()))
        );
    }

    #[test]
    fn validate_http_request_skips_non_json_body_validation() {
        let validator =
            compile_validator(32, vec![r"[;&|`$(){}\[\]<>]".to_owned()], Vec::new(), 1024).unwrap();

        let result = validator
            .validate_http_request(
                vec![("query".to_owned(), "safe".to_owned())],
                "text/plain",
                Some(br#"<script>"#),
            )
            .unwrap();

        assert!(result.is_none());
    }

    #[test]
    fn validate_request_parts_checks_parameters_and_body() {
        let validator = compile_validator(
            32,
            vec![
                r"[;&|`$(){}\[\]<>]".to_owned(),
                r"\.\.[\\/]".to_owned(),
                r"[\x00-\x1f\x7f-\x9f]".to_owned(),
            ],
            Vec::new(),
            1024,
        )
        .unwrap();

        let result = validator
            .validate_request_parts(
                vec![("query".to_owned(), "safe".to_owned())],
                Some(br#"{"name":"<script>"}"#),
            )
            .unwrap();

        assert_eq!(
            result,
            Some(("name".to_owned(), "dangerous_pattern".to_owned()))
        );
    }

    #[test]
    fn dangerous_pattern_matcher_supports_fast_path_rules() {
        let matcher = DangerousPatternMatcher::from_patterns(&[
            r"[;&|`$(){}\[\]<>]".to_owned(),
            r"\.\.[\\/]".to_owned(),
            r"[\x00-\x1f\x7f-\x9f]".to_owned(),
        ])
        .unwrap();

        assert!(matcher.is_match("<script>"));
        assert!(matcher.is_match("../etc/passwd"));
        assert!(matcher.is_match("hello\u{7f}world"));
        assert!(!matcher.is_match("plain-text"));
    }
}
