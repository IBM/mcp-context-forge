use crate::CompiledValidator;
use pyo3::prelude::*;
use regex::Regex;

pub(crate) struct DangerousPatternMatcher {
    pub(crate) shell_metacharacters: bool,
    pub(crate) path_traversal: bool,
    pub(crate) control_characters: bool,
    pub(crate) fallback_pattern: Option<Regex>,
}

impl DangerousPatternMatcher {
    pub(crate) fn from_patterns(patterns: &[String]) -> PyResult<Self> {
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

    pub(crate) fn is_match(&self, value: &str) -> bool {
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

pub(crate) enum ValidationFailure {
    MaxLength,
    DangerousPattern,
}

pub(crate) fn validate_string(
    value: &str,
    validator: &CompiledValidator,
) -> Option<ValidationFailure> {
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
