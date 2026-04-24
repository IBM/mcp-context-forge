mod json;
mod matcher;
mod paths;
mod sanitize;

use json::{validate_json_bytes_streaming, walk_json_like};
use matcher::{DangerousPatternMatcher, ValidationFailure, validate_string};
use paths::{normalize_absolute_path, resolve_allowed_root, validate_resource_path_impl};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;
use sanitize::sanitize_response_body_bytes;
use std::path::PathBuf;

pyo3::create_exception!(
    validation_middleware_rust,
    JsonDepthError,
    pyo3::exceptions::PyValueError
);
pyo3::create_exception!(
    validation_middleware_rust,
    InvalidJsonError,
    pyo3::exceptions::PyValueError
);

#[gen_stub_pyclass]
#[pyclass(name = "Validator")]
pub struct CompiledValidator {
    pub(crate) max_param_length: usize,
    pub(crate) matcher: DangerousPatternMatcher,
    pub(crate) allowed_roots: Vec<PathBuf>,
    pub(crate) max_path_depth: usize,
    pub(crate) max_json_depth: usize,
}

fn compile_validator(
    max_param_length: usize,
    dangerous_patterns: Vec<String>,
    allowed_roots: Vec<String>,
    max_path_depth: usize,
    max_json_depth: usize,
) -> PyResult<CompiledValidator> {
    let matcher = DangerousPatternMatcher::from_patterns(&dangerous_patterns)?;

    Ok(CompiledValidator {
        max_param_length,
        matcher,
        allowed_roots: allowed_roots
            .into_iter()
            .map(PathBuf::from)
            .map(resolve_allowed_root)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>("invalid_path: Invalid path")
            })?
            .into_iter()
            .map(normalize_absolute_path)
            .collect(),
        max_path_depth,
        max_json_depth,
    })
}

#[gen_stub_pymethods]
#[pymethods]
impl CompiledValidator {
    #[new]
    #[pyo3(signature = (max_param_length, dangerous_patterns, allowed_roots=Vec::new(), max_path_depth=1024, max_json_depth=1024))]
    fn new(
        max_param_length: usize,
        dangerous_patterns: Vec<String>,
        allowed_roots: Vec<String>,
        max_path_depth: usize,
        max_json_depth: usize,
    ) -> PyResult<Self> {
        compile_validator(
            max_param_length,
            dangerous_patterns,
            allowed_roots,
            max_path_depth,
            max_json_depth,
        )
    }

    fn validate_json_data(&self, data: &Bound<'_, PyAny>) -> PyResult<Option<(String, String)>> {
        walk_json_like(data.py(), data, self)
    }

    fn validate_json_bytes(
        &self,
        #[gen_stub(override_type(type_repr = "bytes"))] raw_body: &[u8],
    ) -> PyResult<Option<(String, String)>> {
        validate_json_bytes_streaming(raw_body, self)
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

    #[gen_stub(override_return_type(type_repr = "bytes"))]
    fn sanitize_response_body(
        &self,
        #[gen_stub(override_type(type_repr = "bytes"))] body: &[u8],
    ) -> Vec<u8> {
        sanitize_response_body_bytes(body)
    }
}

#[pymodule]
fn validation_middleware_rust(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<CompiledValidator>()?;
    module.add("JsonDepthError", module.py().get_type::<JsonDepthError>())?;
    module.add(
        "InvalidJsonError",
        module.py().get_type::<InvalidJsonError>(),
    )?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::{PyDict, PyList};
    use regex::Regex;

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
            max_json_depth: 1024,
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
                max_json_depth: 1024,
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
                max_json_depth: 1024,
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
    fn walk_json_like_rejects_dangerous_root_string() {
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
                max_json_depth: 1024,
            };

            let payload = pyo3::types::PyString::new(py, "<script>");
            let result = walk_json_like(py, payload.as_any(), &validator).unwrap();
            assert_eq!(
                result,
                Some(("payload".to_owned(), "dangerous_pattern".to_owned()))
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
            max_json_depth: 1024,
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
            max_json_depth: 1024,
        };

        let result = validator
            .validate_json_bytes(b"{\"name\":\"\xC3\xA9\"}")
            .unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn validate_json_bytes_depth_limit_counts_containers_like_python() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
            max_json_depth: 1,
        };

        assert!(
            validator
                .validate_json_bytes(br#"{"name":"safe"}"#)
                .unwrap()
                .is_none()
        );
        assert!(
            validator
                .validate_json_bytes(br#"[1,true,null]"#)
                .unwrap()
                .is_none()
        );
        let err = validator
            .validate_json_bytes(br#"{"nested":{"name":"safe"}}"#)
            .unwrap_err();

        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<JsonDepthError>(py));
        });

        let err = validator.validate_json_bytes(br#"[[1]]"#).unwrap_err();
        Python::attach(|py| {
            assert!(err.is_instance_of::<JsonDepthError>(py));
        });
    }

    #[test]
    fn validate_json_bytes_rejects_trailing_garbage() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
            max_json_depth: 1024,
        };

        let err = validator
            .validate_json_bytes(br#"{"name":"safe"} trailing"#)
            .unwrap_err();

        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
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
            max_json_depth: 1024,
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
        let allowed_root = tempdir.path().canonicalize().unwrap();
        let validator = compile_validator(
            32,
            Vec::new(),
            vec![allowed_root.to_string_lossy().into_owned()],
            1024,
            1024,
        )
        .unwrap();

        let candidate = tempdir.path().join("file.txt");
        let result = validate_resource_path_impl(candidate.to_str().unwrap(), &validator).unwrap();

        assert!(PathBuf::from(result).starts_with(normalize_absolute_path(allowed_root)));
    }

    #[cfg(unix)]
    #[test]
    fn validate_resource_path_accepts_symlink_allowed_root() {
        let real_root = tempfile::tempdir().unwrap();
        let link_parent = tempfile::tempdir().unwrap();
        let link_path = link_parent.path().join("allowed-link");
        std::os::unix::fs::symlink(real_root.path(), &link_path).unwrap();

        let validator = compile_validator(
            32,
            Vec::new(),
            vec![link_path.to_string_lossy().into_owned()],
            1024,
            1024,
        )
        .unwrap();

        let candidate = real_root.path().join("file.txt");
        let result = match validate_resource_path_impl(candidate.to_str().unwrap(), &validator) {
            Ok(path) => path,
            Err(_) => panic!("unexpected path validation failure"),
        };

        assert!(PathBuf::from(result).starts_with(real_root.path().canonicalize().unwrap()));
    }

    #[cfg(unix)]
    #[test]
    fn validate_resource_path_rejects_symlink_escape_from_allowed_root() {
        let tempdir = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let link_path = tempdir.path().join("escape");

        std::os::unix::fs::symlink(outside.path(), &link_path).unwrap();

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
            max_json_depth: 1024,
        };

        let err =
            validate_resource_path_impl(link_path.join("file.txt").to_str().unwrap(), &validator)
                .unwrap_err();
        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
            assert!(err.to_string().contains("Path outside allowed roots"));
        });
    }

    #[cfg(unix)]
    #[test]
    fn validate_resource_path_rejects_broken_symlink_escape_from_allowed_root() {
        let tempdir = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let missing_target = outside.path().join("missing-target");
        let link_path = tempdir.path().join("escape");

        std::os::unix::fs::symlink(&missing_target, &link_path).unwrap();

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
            max_json_depth: 1024,
        };

        let err =
            validate_resource_path_impl(link_path.join("file.txt").to_str().unwrap(), &validator)
                .unwrap_err();
        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
            assert!(err.to_string().contains("Path outside allowed roots"));
        });
    }

    #[cfg(unix)]
    #[test]
    fn validate_resource_path_rejects_chained_symlink_escape_from_allowed_root() {
        let tempdir = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let alias_path = tempdir.path().join("alias");
        let link_path = tempdir.path().join("escape");

        std::os::unix::fs::symlink(outside.path(), &alias_path).unwrap();
        std::os::unix::fs::symlink(&alias_path, &link_path).unwrap();

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
            max_json_depth: 1024,
        };

        let err =
            validate_resource_path_impl(link_path.join("file.txt").to_str().unwrap(), &validator)
                .unwrap_err();
        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
            assert!(err.to_string().contains("Path outside allowed roots"));
        });
    }

    #[test]
    fn validate_resource_path_rejects_embedded_nul() {
        let validator = CompiledValidator {
            max_param_length: 32,
            matcher: DangerousPatternMatcher {
                shell_metacharacters: false,
                path_traversal: false,
                control_characters: false,
                fallback_pattern: None,
            },
            allowed_roots: Vec::new(),
            max_path_depth: 1024,
            max_json_depth: 1024,
        };

        let err = validate_resource_path_impl("bad\0path", &validator).unwrap_err();
        Python::initialize();
        Python::attach(|py| {
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
            assert!(err.to_string().contains("Invalid path"));
        });
    }

    #[test]
    fn sanitize_response_body_removes_control_characters() {
        let sanitized = sanitize_response_body_bytes(b"Hello\x00World\x1f");
        assert_eq!(sanitized, b"HelloWorld");
    }

    #[test]
    fn sanitize_response_body_keeps_safe_ascii_unchanged() {
        let sanitized = sanitize_response_body_bytes(b"plain-ascii-response-body");
        assert_eq!(sanitized, b"plain-ascii-response-body");
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
