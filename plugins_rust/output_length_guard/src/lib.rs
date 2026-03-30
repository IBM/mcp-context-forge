// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Rust acceleration for the Output Length Guard plugin.
//
// Exports `OutputLengthGuardEngine` which processes arbitrary Python containers
// (str, list, dict, nested) and enforces character/token length limits with
// truncate or block strategies.

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;
use std::collections::HashMap;

type PyObject = Py<PyAny>;

// ─── Boundary characters for word-boundary truncation ────────────────────────

const BOUNDARY_CHARS: &[char] = &[
    ' ', '\t', '\n', '\r', '.', ',', ';', ':', '!', '?', '-', '\u{2014}', // em-dash
    '\u{2013}', // en-dash
    '/', '\\', '(', ')', '[', ']', '{', '}',
];

fn is_boundary_char(c: char) -> bool {
    BOUNDARY_CHARS.contains(&c)
}

// ─── Configuration ───────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
struct GuardConfig {
    min_chars: usize,
    max_chars: Option<usize>,
    min_tokens: usize,
    max_tokens: Option<usize>,
    chars_per_token: usize,
    limit_mode: LimitMode,
    strategy: Strategy,
    ellipsis: String,
    word_boundary: bool,
    max_text_length: usize,
    max_structure_size: usize,
    max_recursion_depth: usize,
    max_binary_search_iterations: usize,
}

#[derive(Clone, Debug, PartialEq)]
enum LimitMode {
    Character,
    Token,
}

#[derive(Clone, Debug, PartialEq)]
enum Strategy {
    Truncate,
    Block,
}

impl Default for GuardConfig {
    fn default() -> Self {
        Self {
            min_chars: 0,
            max_chars: None,
            min_tokens: 0,
            max_tokens: None,
            chars_per_token: 4,
            limit_mode: LimitMode::Character,
            strategy: Strategy::Truncate,
            ellipsis: "\u{2026}".to_string(), // "…"
            word_boundary: false,
            max_text_length: 1_000_000,
            max_structure_size: 10_000,
            max_recursion_depth: 100,
            max_binary_search_iterations: 30,
        }
    }
}

impl<'py> TryFrom<&Bound<'py, PyAny>> for GuardConfig {
    type Error = PyErr;

    fn try_from(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        let default = GuardConfig::default();

        let min_chars = obj
            .getattr("min_chars")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.min_chars);

        let max_chars_raw = obj.getattr("max_chars").ok().and_then(|v| {
            if v.is_none() {
                None
            } else {
                v.extract::<usize>().ok()
            }
        });
        // Treat 0 as None (disabled), matching Python validator
        let max_chars = match max_chars_raw {
            Some(0) => None,
            other => other,
        };

        let min_tokens = obj
            .getattr("min_tokens")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.min_tokens);

        let max_tokens_raw = obj.getattr("max_tokens").ok().and_then(|v| {
            if v.is_none() {
                None
            } else {
                v.extract::<usize>().ok()
            }
        });
        let max_tokens = match max_tokens_raw {
            Some(0) => None,
            other => other,
        };

        let chars_per_token = obj
            .getattr("chars_per_token")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.chars_per_token)
            .clamp(1, 10);

        let limit_mode_str: String = obj
            .getattr("limit_mode")
            .ok()
            .and_then(|v| v.extract::<String>().ok())
            .unwrap_or_else(|| "character".to_string());
        let limit_mode = if limit_mode_str.trim().eq_ignore_ascii_case("token") {
            LimitMode::Token
        } else {
            LimitMode::Character
        };

        let strategy_str: String = obj
            .getattr("strategy")
            .ok()
            .and_then(|v| v.extract::<String>().ok())
            .unwrap_or_else(|| "truncate".to_string());
        let strategy = if strategy_str.trim().eq_ignore_ascii_case("block") {
            Strategy::Block
        } else {
            Strategy::Truncate
        };

        let ellipsis = obj
            .getattr("ellipsis")
            .ok()
            .and_then(|v| v.extract::<String>().ok())
            .unwrap_or(default.ellipsis);

        let word_boundary = obj
            .getattr("word_boundary")
            .ok()
            .and_then(|v| v.extract::<bool>().ok())
            .unwrap_or(default.word_boundary);

        let max_text_length = obj
            .getattr("max_text_length")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_text_length);

        let max_structure_size = obj
            .getattr("max_structure_size")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_structure_size);

        let max_recursion_depth = obj
            .getattr("max_recursion_depth")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_recursion_depth);

        let max_binary_search_iterations = obj
            .getattr("max_binary_search_iterations")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_binary_search_iterations);

        Ok(Self {
            min_chars,
            max_chars,
            min_tokens,
            max_tokens,
            chars_per_token,
            limit_mode,
            strategy,
            ellipsis,
            word_boundary,
            max_text_length,
            max_structure_size,
            max_recursion_depth,
            max_binary_search_iterations,
        })
    }
}

// ─── Pure functions (no PyO3 dependency) ─────────────────────────────────────

/// Check if a string represents a numeric value (int, float, scientific notation).
fn is_numeric_string(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    text.parse::<f64>().is_ok()
}

/// Estimate token count: chars / chars_per_token (integer division).
fn estimate_tokens(text_len: usize, chars_per_token: usize) -> usize {
    if chars_per_token == 0 {
        return 0;
    }
    text_len / chars_per_token
}

/// Find word boundary position by scanning backward from `cut`.
/// Returns position after the boundary character, or `cut` if none found.
fn find_word_boundary(value: &str, cut: usize, max_chars: usize) -> usize {
    if cut == 0 || value.is_empty() {
        return cut;
    }

    // Clamp cut to string length (in chars)
    let char_count = value.chars().count();
    let cut = cut.min(char_count);

    // Search range: go back at most 20% of max_chars
    let min_search = cut.saturating_sub((max_chars as f64 * 0.2) as usize);

    // Collect chars for indexed access
    let chars: Vec<char> = value.chars().collect();

    for i in (min_search..cut).rev() {
        if is_boundary_char(chars[i]) {
            return i + 1; // Position after boundary char
        }
    }

    cut // No boundary found
}

/// Binary search to find character position that fits within a token budget.
fn find_token_cut_point(
    text_char_count: usize,
    max_tokens: usize,
    chars_per_token: usize,
    max_iterations: usize,
) -> usize {
    if max_tokens == 0 || chars_per_token == 0 {
        return 0;
    }

    let right_bound = text_char_count.min(max_tokens * chars_per_token + 100);
    let mut left: usize = 0;
    let mut right = right_bound;
    let mut best_cut: usize = 0;
    let mut iterations: usize = 0;

    while left <= right && iterations < max_iterations {
        iterations += 1;
        let mid = (left + right) / 2;
        let estimated_tokens = mid / chars_per_token;

        if estimated_tokens <= max_tokens {
            best_cut = mid;
            if mid == right {
                break;
            }
            left = mid + 1;
        } else {
            if mid == 0 {
                break;
            }
            right = mid - 1;
        }
    }

    best_cut
}

/// Truncate a string to fit within limits.
/// Operates on chars (not bytes) to handle Unicode correctly.
fn truncate(value: &str, cfg: &GuardConfig) -> String {
    let ell = &cfg.ellipsis;

    // Token-based truncation
    if cfg.limit_mode == LimitMode::Token {
        if let Some(max_tokens) = cfg.max_tokens {
            if max_tokens == 0 {
                return value.to_string();
            }
            let char_count = value.chars().count();
            let estimated_tokens = estimate_tokens(char_count, cfg.chars_per_token);

            if estimated_tokens > max_tokens {
                let mut cut = find_token_cut_point(
                    char_count,
                    max_tokens,
                    cfg.chars_per_token,
                    cfg.max_binary_search_iterations,
                );

                if cfg.word_boundary && cut > 0 {
                    cut = find_word_boundary(value, cut, cut);
                }

                let truncated: String = value.chars().take(cut).collect();
                return truncated + ell;
            }
        }
        // Under limit or no max_tokens — pass through
        return value.to_string();
    }

    // Character-based truncation
    if cfg.limit_mode != LimitMode::Character {
        return value.to_string();
    }

    let max_chars = match cfg.max_chars {
        Some(0) | None => return value.to_string(),
        Some(m) => m,
    };

    let char_count = value.chars().count();
    if char_count <= max_chars {
        return value.to_string();
    }

    let ell_len = ell.chars().count();
    if ell_len >= max_chars {
        return value.chars().take(max_chars).collect();
    }

    let mut cut = max_chars - ell_len;

    if cfg.word_boundary && cut > 0 {
        cut = find_word_boundary(value, cut, max_chars);
    }

    let truncated: String = value.chars().take(cut).collect();
    truncated + ell
}

// ─── Violation info (returned as Python dict) ────────────────────────────────

struct ViolationInfo {
    reason: String,
    description: String,
    code: String,
    details: HashMap<String, ViolationValue>,
    http_status_code: i32,
    mcp_error_code: i32,
}

#[derive(Clone)]
enum ViolationValue {
    Str(String),
    Int(i64),
    #[allow(dead_code)]
    OptInt(Option<i64>),
}

impl ViolationInfo {
    fn to_py_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("reason", &self.reason)?;
        dict.set_item("description", &self.description)?;
        dict.set_item("code", &self.code)?;
        dict.set_item("http_status_code", self.http_status_code)?;
        dict.set_item("mcp_error_code", self.mcp_error_code)?;

        let details = PyDict::new(py);
        for (k, v) in &self.details {
            match v {
                ViolationValue::Str(s) => details.set_item(k, s)?,
                ViolationValue::Int(i) => details.set_item(k, i)?,
                ViolationValue::OptInt(opt) => match opt {
                    Some(i) => details.set_item(k, i)?,
                    None => details.set_item(k, py.None())?,
                },
            }
        }
        dict.set_item("details", details)?;
        Ok(dict)
    }
}

// ─── Recursive container processing ──────────────────────────────────────────

/// Result of processing a container.
enum ProcessResult<'py> {
    /// Container was unchanged.
    Unchanged,
    /// Container was modified; the new value is wrapped.
    Modified(Bound<'py, PyAny>),
    /// A violation was triggered (block mode).
    Violation(ViolationInfo),
}

/// Recursively process a Python container (str, list, dict, nested).
/// Returns ProcessResult indicating what happened.
fn process_container<'py>(
    py: Python<'py>,
    container: &Bound<'py, PyAny>,
    cfg: &GuardConfig,
    path: &str,
    depth: usize,
) -> PyResult<ProcessResult<'py>> {
    // Security: depth limit
    if depth > cfg.max_recursion_depth {
        return Ok(ProcessResult::Unchanged);
    }

    // ── String leaf ──
    if let Ok(text) = container.extract::<String>() {
        // Skip numeric strings
        if is_numeric_string(&text) {
            return Ok(ProcessResult::Unchanged);
        }

        let char_count = text.chars().count();
        let token_count = estimate_tokens(char_count, cfg.chars_per_token);

        // Determine if out of bounds based on limit_mode
        let (below_min, above_max) = match cfg.limit_mode {
            LimitMode::Character => {
                let below = cfg.min_chars > 0 && char_count < cfg.min_chars;
                let above = cfg.max_chars.is_some_and(|m| char_count > m);
                (below, above)
            }
            LimitMode::Token => {
                let below = cfg.min_tokens > 0 && token_count < cfg.min_tokens;
                let above = cfg.max_tokens.is_some_and(|m| token_count > m);
                (below, above)
            }
        };

        if !below_min && !above_max {
            return Ok(ProcessResult::Unchanged);
        }

        // Block strategy
        if cfg.strategy == Strategy::Block {
            let location = if path.is_empty() {
                String::new()
            } else {
                format!(" at {path}")
            };

            let preview = if text.chars().count() > 50 {
                let p: String = text.chars().take(50).collect();
                p + "..."
            } else {
                text.clone()
            };

            let (reason, description, code, details) = if cfg.limit_mode == LimitMode::Token
                && above_max
            {
                let max_t = cfg.max_tokens.unwrap_or(0) as i64;
                let mut d = HashMap::new();
                d.insert(
                    "token_count".to_string(),
                    ViolationValue::Int(token_count as i64),
                );
                d.insert("max_tokens".to_string(), ViolationValue::Int(max_t));
                d.insert(
                    "chars_per_token".to_string(),
                    ViolationValue::Int(cfg.chars_per_token as i64),
                );
                d.insert(
                    "strategy".to_string(),
                    ViolationValue::Str("block".to_string()),
                );
                d.insert(
                    "location".to_string(),
                    ViolationValue::Str(if path.is_empty() {
                        "root".to_string()
                    } else {
                        path.to_string()
                    }),
                );
                d.insert("value_preview".to_string(), ViolationValue::Str(preview));
                (
                    format!("Output length out of bounds{location}"),
                    format!("Token count {token_count} exceeds max_tokens {max_t}{location}"),
                    "OUTPUT_LENGTH_VIOLATION".to_string(),
                    d,
                )
            } else if above_max {
                let max_c = cfg.max_chars.unwrap_or(0) as i64;
                let mut d = HashMap::new();
                d.insert("length".to_string(), ViolationValue::Int(char_count as i64));
                d.insert("max_chars".to_string(), ViolationValue::Int(max_c));
                d.insert(
                    "strategy".to_string(),
                    ViolationValue::Str("block".to_string()),
                );
                d.insert(
                    "location".to_string(),
                    ViolationValue::Str(if path.is_empty() {
                        "root".to_string()
                    } else {
                        path.to_string()
                    }),
                );
                d.insert("value_preview".to_string(), ViolationValue::Str(preview));
                (
                    format!("Output length out of bounds{location}"),
                    format!("String length {char_count} exceeds max_chars {max_c}{location}"),
                    "OUTPUT_LENGTH_VIOLATION".to_string(),
                    d,
                )
            } else {
                // Min violation
                let mut d = HashMap::new();
                d.insert("length".to_string(), ViolationValue::Int(char_count as i64));
                d.insert(
                    "min_chars".to_string(),
                    ViolationValue::Int(cfg.min_chars as i64),
                );
                d.insert(
                    "token_count".to_string(),
                    ViolationValue::Int(token_count as i64),
                );
                d.insert(
                    "min_tokens".to_string(),
                    ViolationValue::Int(cfg.min_tokens as i64),
                );
                d.insert(
                    "location".to_string(),
                    ViolationValue::Str(if path.is_empty() {
                        "root".to_string()
                    } else {
                        path.to_string()
                    }),
                );
                (
                    format!("Output length out of bounds{location}"),
                    format!(
                        "String length {char_count} or tokens {token_count} below minimum{location}"
                    ),
                    "OUTPUT_LENGTH_VIOLATION".to_string(),
                    d,
                )
            };

            return Ok(ProcessResult::Violation(ViolationInfo {
                reason,
                description,
                code,
                details,
                http_status_code: 422,
                mcp_error_code: -32000,
            }));
        }

        // Truncate strategy — only truncate if above max
        if above_max {
            let truncated = truncate(&text, cfg);
            if truncated != text {
                let py_str = PyString::new(py, &truncated);
                return Ok(ProcessResult::Modified(py_str.into_any()));
            }
        }

        return Ok(ProcessResult::Unchanged);
    }

    // ── List ──
    if let Ok(list) = container.cast::<PyList>() {
        if list.len() > cfg.max_structure_size {
            return Ok(ProcessResult::Unchanged);
        }

        let mut any_modified = false;
        let new_list = PyList::empty(py);

        for (idx, item) in list.iter().enumerate() {
            let item_path = if path.is_empty() {
                format!("[{idx}]")
            } else {
                format!("{path}[{idx}]")
            };

            match process_container(py, &item, cfg, &item_path, depth + 1)? {
                ProcessResult::Violation(v) => return Ok(ProcessResult::Violation(v)),
                ProcessResult::Modified(new_val) => {
                    any_modified = true;
                    new_list.append(new_val)?;
                }
                ProcessResult::Unchanged => {
                    new_list.append(item)?;
                }
            }
        }

        if any_modified {
            return Ok(ProcessResult::Modified(new_list.into_any()));
        }
        return Ok(ProcessResult::Unchanged);
    }

    // ── Dict ──
    if let Ok(dict) = container.cast::<PyDict>() {
        if dict.len() > cfg.max_structure_size {
            return Ok(ProcessResult::Unchanged);
        }

        let mut any_modified = false;
        let new_dict = PyDict::new(py);

        for (key, value) in dict.iter() {
            let key_str: String = key.extract::<String>().unwrap_or_else(|_| format!("{key}"));
            let value_path = if path.is_empty() {
                key_str.clone()
            } else {
                format!("{path}.{key_str}")
            };

            match process_container(py, &value, cfg, &value_path, depth + 1)? {
                ProcessResult::Violation(v) => return Ok(ProcessResult::Violation(v)),
                ProcessResult::Modified(new_val) => {
                    any_modified = true;
                    new_dict.set_item(&key, new_val)?;
                }
                ProcessResult::Unchanged => {
                    new_dict.set_item(&key, value)?;
                }
            }
        }

        if any_modified {
            return Ok(ProcessResult::Modified(new_dict.into_any()));
        }
        return Ok(ProcessResult::Unchanged);
    }

    // ── Other types (int, bool, None, etc.) — pass through ──
    Ok(ProcessResult::Unchanged)
}

// ─── PyO3 exports ────────────────────────────────────────────────────────────

/// High-performance output length guard engine.
///
/// Parses configuration once at init; reuses it across process() calls.
#[gen_stub_pyclass]
#[pyclass]
pub struct OutputLengthGuardEngine {
    cfg: GuardConfig,
}

#[gen_stub_pymethods]
#[pymethods]
impl OutputLengthGuardEngine {
    /// Create a new engine from a Python config object (OutputLengthGuardConfig).
    #[new]
    pub fn new(config: &Bound<'_, PyAny>) -> PyResult<Self> {
        let cfg = GuardConfig::try_from(config)?;
        Ok(Self { cfg })
    }

    /// Process a Python container and enforce length limits.
    ///
    /// Returns a tuple: (modified_container_or_None, was_modified, violation_dict_or_None)
    ///
    /// - If unchanged: (None, False, None)
    /// - If modified:  (new_container, True, None)
    /// - If violation: (None, False, violation_dict)
    pub fn process<'py>(
        &self,
        py: Python<'py>,
        container: &Bound<'py, PyAny>,
    ) -> PyResult<(PyObject, bool, PyObject)> {
        match process_container(py, container, &self.cfg, "", 0)? {
            ProcessResult::Unchanged => Ok((py.None(), false, py.None())),
            ProcessResult::Modified(new_val) => Ok((new_val.unbind(), true, py.None())),
            ProcessResult::Violation(v) => {
                let dict = v.to_py_dict(py)?;
                Ok((py.None(), false, dict.unbind().into()))
            }
        }
    }

    /// Truncate a single string according to the engine's config.
    /// Convenience method for direct string processing.
    pub fn truncate_string(&self, value: &str) -> String {
        truncate(value, &self.cfg)
    }

    /// Estimate token count for a string.
    pub fn estimate_tokens(&self, text: &str) -> usize {
        estimate_tokens(text.chars().count(), self.cfg.chars_per_token)
    }
}

/// Standalone function for backward compatibility.
/// Creates a temporary engine from the config and processes the container.
#[gen_stub_pyfunction]
#[pyfunction]
fn py_process_container<'py>(
    py: Python<'py>,
    container: &Bound<'py, PyAny>,
    config: &Bound<'py, PyAny>,
) -> PyResult<(PyObject, bool, PyObject)> {
    let cfg = GuardConfig::try_from(config)?;
    let engine = OutputLengthGuardEngine { cfg };
    engine.process(py, container)
}

#[pymodule]
fn output_length_guard_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<OutputLengthGuardEngine>()?;
    m.add_function(wrap_pyfunction!(py_process_container, m)?)?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── is_numeric_string ──

    #[test]
    fn test_numeric_integers() {
        assert!(is_numeric_string("123"));
        assert!(is_numeric_string("-42"));
        assert!(is_numeric_string("0"));
    }

    #[test]
    fn test_numeric_floats() {
        assert!(is_numeric_string("123.45"));
        assert!(is_numeric_string("-0.5"));
        assert!(is_numeric_string("0.0"));
    }

    #[test]
    fn test_numeric_scientific() {
        assert!(is_numeric_string("6.022e23"));
        assert!(is_numeric_string("1.23e-4"));
        assert!(is_numeric_string("5E+10"));
    }

    #[test]
    fn test_non_numeric() {
        assert!(!is_numeric_string("hello"));
        assert!(!is_numeric_string("12abc"));
        assert!(!is_numeric_string(""));
        assert!(!is_numeric_string("not a number"));
    }

    // ── estimate_tokens ──

    #[test]
    fn test_estimate_tokens_basic() {
        // "Hello world! This is a test." = 28 chars, 28/4 = 7
        assert_eq!(estimate_tokens(28, 4), 7);
    }

    #[test]
    fn test_estimate_tokens_empty() {
        assert_eq!(estimate_tokens(0, 4), 0);
    }

    #[test]
    fn test_estimate_tokens_single_char() {
        assert_eq!(estimate_tokens(1, 4), 0);
    }

    #[test]
    fn test_estimate_tokens_exact_ratio() {
        assert_eq!(estimate_tokens(4, 4), 1);
    }

    #[test]
    fn test_estimate_tokens_custom_ratio() {
        assert_eq!(estimate_tokens(12, 3), 4);
    }

    #[test]
    fn test_estimate_tokens_min_ratio() {
        assert_eq!(estimate_tokens(5, 1), 5);
    }

    #[test]
    fn test_estimate_tokens_max_ratio() {
        assert_eq!(estimate_tokens(28, 10), 2);
    }

    #[test]
    fn test_estimate_tokens_zero_ratio() {
        assert_eq!(estimate_tokens(100, 0), 0);
    }

    // ── find_word_boundary ──

    #[test]
    fn test_word_boundary_basic() {
        // "Hello world", pos=7 (in "world") -> finds space at 5, returns 6
        assert_eq!(find_word_boundary("Hello world", 7, 100), 6);
    }

    #[test]
    fn test_word_boundary_at_space() {
        // pos=5 is 'space' itself; searching backward from pos-1=4 finds no boundary
        // in the range, so returns cut (5)
        assert_eq!(find_word_boundary("Hello world", 5, 100), 5);
    }

    #[test]
    fn test_word_boundary_start() {
        assert_eq!(find_word_boundary("Hello world", 0, 100), 0);
    }

    #[test]
    fn test_word_boundary_end() {
        // pos=11 (len), searches backward, finds space at 5, returns 6
        assert_eq!(find_word_boundary("Hello world", 11, 100), 6);
    }

    #[test]
    fn test_word_boundary_no_spaces() {
        assert_eq!(find_word_boundary("HelloWorld", 5, 100), 5);
    }

    #[test]
    fn test_word_boundary_multiple_spaces() {
        // "Hello    world", pos=10 -> last space is at 8, returns 9
        assert_eq!(find_word_boundary("Hello    world", 10, 100), 9);
    }

    #[test]
    fn test_word_boundary_punctuation() {
        // "Hello, world!", pos=9 -> space at 6, returns 7
        assert_eq!(find_word_boundary("Hello, world!", 9, 100), 7);
    }

    #[test]
    fn test_word_boundary_newline() {
        // "Hello\nworld", pos=8 -> newline at 5, returns 6
        assert_eq!(find_word_boundary("Hello\nworld", 8, 100), 6);
    }

    #[test]
    fn test_word_boundary_tab() {
        // "Hello\tworld", pos=8 -> tab at 5, returns 6
        assert_eq!(find_word_boundary("Hello\tworld", 8, 100), 6);
    }

    #[test]
    fn test_word_boundary_unicode() {
        // "Hello 世界", pos=8 -> space at 5, returns 6
        assert_eq!(find_word_boundary("Hello \u{4e16}\u{754c}", 8, 100), 6);
    }

    // ── find_token_cut_point ──

    #[test]
    fn test_cut_point_basic() {
        // 28 chars, max 3 tokens at ratio 4 -> cut <= 12+padding
        let cut = find_token_cut_point(28, 3, 4, 30);
        assert!(cut > 0 && cut <= 28);
        assert!(cut / 4 <= 3);
    }

    #[test]
    fn test_cut_point_exact_fit() {
        // 16 chars = 4 tokens at ratio 4 -> cut should be 16
        let cut = find_token_cut_point(16, 4, 4, 30);
        assert_eq!(cut, 16);
    }

    #[test]
    fn test_cut_point_under_limit() {
        // 5 chars = 1 token, limit 10 -> cut should be 5
        let cut = find_token_cut_point(5, 10, 4, 30);
        assert_eq!(cut, 5);
    }

    #[test]
    fn test_cut_point_zero_tokens() {
        let cut = find_token_cut_point(12, 0, 4, 30);
        assert_eq!(cut, 0);
    }

    #[test]
    fn test_cut_point_one_token() {
        let cut = find_token_cut_point(100, 1, 4, 30);
        assert!(cut / 4 <= 1);
    }

    #[test]
    fn test_cut_point_large_text() {
        let cut = find_token_cut_point(100_000, 100, 4, 30);
        assert!(cut / 4 <= 100);
    }

    #[test]
    fn test_cut_point_custom_ratio() {
        let cut = find_token_cut_point(28, 5, 3, 30);
        assert!(cut / 3 <= 5);
    }

    // ── truncate ──

    fn make_cfg(
        limit_mode: LimitMode,
        max_chars: Option<usize>,
        max_tokens: Option<usize>,
        chars_per_token: usize,
        ellipsis: &str,
        word_boundary: bool,
    ) -> GuardConfig {
        GuardConfig {
            limit_mode,
            max_chars,
            max_tokens,
            chars_per_token,
            ellipsis: ellipsis.to_string(),
            word_boundary,
            ..GuardConfig::default()
        }
    }

    #[test]
    fn test_truncate_char_mode_basic() {
        let cfg = make_cfg(LimitMode::Character, Some(10), None, 4, "...", false);
        let result = truncate("Hello world! This is a test.", &cfg);
        assert!(result.len() <= 10);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_char_mode_under_limit() {
        let cfg = make_cfg(LimitMode::Character, Some(100), None, 4, "...", false);
        let result = truncate("Hello", &cfg);
        assert_eq!(result, "Hello");
    }

    #[test]
    fn test_truncate_char_mode_with_word_boundary() {
        let cfg = make_cfg(LimitMode::Character, Some(15), None, 4, "...", true);
        let result = truncate("Hello world! This is a test.", &cfg);
        assert!(result.len() <= 15);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_char_mode_none_max() {
        let cfg = make_cfg(LimitMode::Character, None, None, 4, "...", false);
        let result = truncate("Hello world!", &cfg);
        assert_eq!(result, "Hello world!");
    }

    #[test]
    fn test_truncate_char_mode_zero_max() {
        let cfg = make_cfg(LimitMode::Character, Some(0), None, 4, "...", false);
        let result = truncate("Hello world!", &cfg);
        // 0 is treated as None (disabled)
        assert_eq!(result, "Hello world!");
    }

    #[test]
    fn test_truncate_token_mode_basic() {
        let cfg = make_cfg(LimitMode::Token, None, Some(3), 4, "...", false);
        let text = "Hello world! This is a test.";
        let result = truncate(text, &cfg);
        assert_ne!(result, text);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_token_mode_under_limit() {
        let cfg = make_cfg(LimitMode::Token, None, Some(10), 4, "...", false);
        let result = truncate("Hello", &cfg);
        assert_eq!(result, "Hello");
    }

    #[test]
    fn test_truncate_token_mode_exact_limit() {
        // 16 chars = 4 tokens at ratio 4
        let cfg = make_cfg(LimitMode::Token, None, Some(4), 4, "...", false);
        let result = truncate("1234567890123456", &cfg);
        assert_eq!(result, "1234567890123456");
    }

    #[test]
    fn test_truncate_token_mode_zero_limit() {
        // 0 treated as disabled
        let cfg = make_cfg(LimitMode::Token, None, Some(0), 4, "...", false);
        let result = truncate("Hello world!", &cfg);
        assert_eq!(result, "Hello world!");
    }

    #[test]
    fn test_truncate_token_mode_none_limit() {
        let cfg = make_cfg(LimitMode::Token, None, None, 4, "...", false);
        let result = truncate("Hello world!", &cfg);
        assert_eq!(result, "Hello world!");
    }

    #[test]
    fn test_truncate_token_with_word_boundary() {
        let cfg = make_cfg(LimitMode::Token, None, Some(3), 4, "...", true);
        let text = "Hello world! This is a test.";
        let result = truncate(text, &cfg);
        assert_ne!(result, text);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_token_with_ellipsis() {
        let cfg = make_cfg(LimitMode::Token, None, Some(2), 4, "...", false);
        let text = "Hello world! This is a test.";
        let result = truncate(text, &cfg);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_unicode() {
        let text = "Hello \u{4e16}\u{754c}! \u{1f30d} ".repeat(10);
        let cfg = make_cfg(LimitMode::Token, None, Some(5), 4, "...", false);
        let result = truncate(&text, &cfg);
        assert_ne!(result, text);
    }

    #[test]
    fn test_truncate_char_custom_ellipsis() {
        let cfg = make_cfg(LimitMode::Character, Some(15), None, 4, "\u{2026}", false);
        let result = truncate("Hello world! This is a test.", &cfg);
        assert!(result.ends_with('\u{2026}'));
        assert!(result.chars().count() <= 15);
    }

    // ── Mode segregation (mirrors Python limit_mode tests) ──

    #[test]
    fn test_character_mode_ignores_tokens() {
        // In character mode, even if token limit would trigger, only chars matter
        let cfg = make_cfg(LimitMode::Character, Some(100), Some(1), 4, "...", false);
        let result = truncate("Hello world! This is a test.", &cfg);
        // 28 chars < 100 max_chars, so no truncation even though tokens > 1
        assert_eq!(result, "Hello world! This is a test.");
    }

    #[test]
    fn test_token_mode_ignores_chars() {
        // In token mode, even if char limit would trigger, only tokens matter
        let cfg = make_cfg(LimitMode::Token, Some(5), Some(100), 4, "...", false);
        let result = truncate("Hello world! This is a test.", &cfg);
        // 7 tokens < 100 max_tokens, so no truncation even though chars > 5
        assert_eq!(result, "Hello world! This is a test.");
    }

    // ── Large text performance ──

    #[test]
    fn test_truncate_large_text() {
        let text = "a".repeat(100_000);
        let cfg = make_cfg(LimitMode::Character, Some(1000), None, 4, "...", false);
        let result = truncate(&text, &cfg);
        assert!(result.len() <= 1000);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_large_text_tokens() {
        let text = "a".repeat(100_000);
        let cfg = make_cfg(LimitMode::Token, None, Some(100), 4, "...", false);
        let result = truncate(&text, &cfg);
        assert_ne!(result, text);
        // 100 tokens * 4 chars = ~400 chars + ellipsis
        assert!(result.len() < 500);
    }
}
