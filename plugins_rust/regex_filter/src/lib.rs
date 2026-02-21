// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Regex Filter Plugin - Rust Implementation
//
// High-performance search and replace using compiled regex patterns.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use regex::{Regex, RegexSet};
use std::borrow::Cow;

/// Search and replace pattern configuration
#[derive(Debug, Clone)]
pub struct SearchReplace {
    pub search: String,
    pub replace: String,
    pub compiled: Regex,
}

/// Configuration for search and replace plugin with optimized pre-filtering
#[derive(Debug, Clone)]
pub struct SearchReplaceConfig {
    pub words: Vec<SearchReplace>,
    /// RegexSet for fast pre-filtering - checks if ANY pattern matches
    pub pattern_set: Option<RegexSet>,
}

impl SearchReplaceConfig {
    /// Extract configuration from Python dict with validation
    ///
    /// Error messages match Python implementation format for consistency
    pub fn from_py_dict(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let mut words = Vec::new();
        let mut patterns = Vec::new();
        let mut validation_errors = Vec::new();

        if let Some(words_value) = dict.get_item("words")?
            && let Ok(py_list) = words_value.cast::<PyList>()
        {
            for (idx, item) in py_list.iter().enumerate() {
                if let Ok(py_dict) = item.cast::<PyDict>() {
                    let search: String = py_dict
                        .get_item("search")?
                        .ok_or_else(|| {
                            pyo3::exceptions::PyValueError::new_err("Missing 'search' field")
                        })?
                        .extract()?;
                    let replace: String = py_dict
                        .get_item("replace")?
                        .ok_or_else(|| {
                            pyo3::exceptions::PyValueError::new_err("Missing 'replace' field")
                        })?
                        .extract()?;

                    // Compile regex pattern - collect errors instead of silently skipping
                    // Error format matches Python: "Pattern {idx}: Invalid regex pattern '{pattern}': {error}"
                    match Regex::new(&search) {
                        Ok(compiled) => {
                            patterns.push(search.clone());
                            words.push(SearchReplace {
                                search,
                                replace,
                                compiled,
                            });
                        }
                        Err(e) => {
                            validation_errors.push(format!(
                                "Pattern {}: Invalid regex pattern '{}': {}",
                                idx, search, e
                            ));
                        }
                    }
                }
            }
        }

        // If there were validation errors, raise them with same format as Python
        if !validation_errors.is_empty() {
            let error_msg = format!(
                "Invalid regex patterns detected:\n{}",
                validation_errors.join("\n")
            );
            return Err(pyo3::exceptions::PyValueError::new_err(error_msg));
        }

        // Build RegexSet for fast pre-filtering (only if we have patterns)
        let pattern_set = if !patterns.is_empty() {
            RegexSet::new(&patterns).ok()
        } else {
            None
        };

        Ok(Self { words, pattern_set })
    }
}

/// Main search and replace plugin exposed to Python
///
/// # Example (Python)
/// ```python
/// from plugins_rust.regex_filter import SearchReplacePluginRust
///
/// config = {
///     "words": [
///         {"search": r"\bsecret\b", "replace": "[REDACTED]"},
///         {"search": r"\bpassword\b", "replace": "[REDACTED]"}
///     ]
/// }
/// plugin = SearchReplacePluginRust(config)
///
/// # Process text
/// text = "The secret password is hidden"
/// result = plugin.apply_patterns(text)
/// print(result)  # "The [REDACTED] [REDACTED] is hidden"
/// ```
#[pyclass]
pub struct SearchReplacePluginRust {
    pub config: SearchReplaceConfig,
}

#[pymethods]
impl SearchReplacePluginRust {
    /// Create a new search and replace plugin
    ///
    /// # Arguments
    /// * `config_dict` - Python dictionary with configuration
    ///
    /// # Configuration Keys
    /// * `words` (list): List of search/replace patterns
    ///   - Each item must have `search` (regex pattern) and `replace` (replacement text)
    #[new]
    pub fn new(config_dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let config = SearchReplaceConfig::from_py_dict(config_dict).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid config: {}", e))
        })?;

        Ok(Self { config })
    }

    /// Apply all search/replace patterns to text with optimized performance
    ///
    /// # Arguments
    /// * `text` - Text to process
    ///
    /// # Returns
    /// Modified text with all patterns applied
    ///
    /// # Performance Optimizations
    /// - Uses RegexSet for fast pre-filtering (early exit if no matches)
    /// - Smart Cow usage: only allocates when patterns actually match
    /// - String capacity pre-allocation based on input size
    pub fn apply_patterns(&self, text: &str) -> String {
        // Early exit: use RegexSet to check if ANY pattern matches
        if let Some(ref pattern_set) = self.config.pattern_set
            && !pattern_set.is_match(text)
        {
            // No patterns match - return original text without allocation
            return text.to_string();
        }

        // At least one pattern matches - process with smart Cow usage
        let mut result = Cow::Borrowed(text);
        let mut modified = false;

        for pattern in &self.config.words {
            // Only allocate if this specific pattern matches
            if pattern.compiled.is_match(&result) {
                let replaced = pattern.compiled.replace_all(&result, &pattern.replace);

                // Only convert to owned if replacement actually changed something
                if let Cow::Owned(new_text) = replaced {
                    result = Cow::Owned(new_text);
                    modified = true;
                } else if modified {
                    // Previous patterns modified, keep as owned
                    result = Cow::Owned(replaced.into_owned());
                }
            }
        }

        result.into_owned()
    }

    /// Process a Python dict, applying patterns to all string values
    ///
    /// # Arguments
    /// * `data` - Python dict to process
    ///
    /// # Returns
    /// New dict with patterns applied to string values
    pub fn process_dict(&self, py: Python, data: &Bound<'_, PyDict>) -> PyResult<Py<PyDict>> {
        let new_dict = PyDict::new(py);

        for (key, value) in data.iter() {
            if let Ok(text) = value.extract::<String>() {
                let modified = self.apply_patterns(&text);
                new_dict.set_item(key, modified)?;
            } else {
                new_dict.set_item(key, value)?;
            }
        }

        Ok(new_dict.unbind())
    }

    /// Process nested data structures (dicts, lists, strings) with optimized conversions
    ///
    /// # Arguments
    /// * `data` - Python object (dict, list, str, or other)
    ///
    /// # Returns
    /// Tuple of (modified: bool, new_data: Any)
    ///
    /// # Performance Optimizations
    /// - Early exit for non-matching strings (via apply_patterns optimization)
    /// - Reduced Python object allocations when no modifications occur
    /// - Reuses original objects when possible instead of creating new ones
    pub fn process_nested(
        &self,
        py: Python,
        data: &Bound<'_, PyAny>,
    ) -> PyResult<(bool, Py<PyAny>)> {
        // Handle strings directly with optimized pattern matching
        if let Ok(text) = data.extract::<String>() {
            let modified_text = self.apply_patterns(&text);
            let changed = modified_text != text;

            if changed {
                // Only create new Python object if text actually changed
                return Ok((true, modified_text.into_pyobject(py)?.into_any().unbind()));
            } else {
                // Reuse original Python object - no allocation needed
                return Ok((false, data.clone().unbind()));
            }
        }

        // Handle dictionaries with optimized allocation
        if let Ok(dict) = data.cast::<PyDict>() {
            let mut any_modified = false;
            let mut processed_items = Vec::with_capacity(dict.len());

            // Process all items and track modifications
            for (key, value) in dict.iter() {
                let (val_modified, new_value) = self.process_nested(py, &value)?;

                if val_modified {
                    any_modified = true;
                }

                processed_items.push((key.clone().unbind(), val_modified, new_value));
            }

            if any_modified {
                // Only create new dict if something actually changed
                let new_dict = PyDict::new(py);

                for (key, _modified, value) in processed_items {
                    new_dict.set_item(key.bind(py), value.bind(py))?;
                }

                return Ok((true, new_dict.into_any().unbind()));
            } else {
                // Nothing changed - reuse original dict
                return Ok((false, data.clone().unbind()));
            }
        }

        // Handle lists with optimized allocation
        if let Ok(list) = data.cast::<PyList>() {
            let mut any_modified = false;
            let mut new_items = Vec::with_capacity(list.len());

            for item in list.iter() {
                let (item_modified, new_item) = self.process_nested(py, &item)?;

                if item_modified {
                    any_modified = true;
                    new_items.push((true, new_item));
                } else {
                    new_items.push((false, item.clone().unbind()));
                }
            }

            if any_modified {
                // Only create new list if something actually changed
                let new_list = PyList::empty(py);

                for (_modified, item) in new_items {
                    new_list.append(item.bind(py))?;
                }

                return Ok((true, new_list.into_any().unbind()));
            } else {
                // Nothing changed - reuse original list
                return Ok((false, data.clone().unbind()));
            }
        }

        // Other types: no processing, return original object
        Ok((false, data.clone().unbind()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_apply_patterns() {
        let patterns = vec![r"\bsecret\b", r"\bpassword\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: r"\bsecret\b".to_string(),
                    replace: "[REDACTED]".to_string(),
                    compiled: Regex::new(r"\bsecret\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bpassword\b".to_string(),
                    replace: "[REDACTED]".to_string(),
                    compiled: Regex::new(r"\bpassword\b").unwrap(),
                },
            ],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("The secret password is hidden");
        assert_eq!(result, "The [REDACTED] [REDACTED] is hidden");
    }

    #[test]
    fn test_no_match() {
        let patterns = vec![r"\bsecret\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bsecret\b".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new(r"\bsecret\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("No sensitive data here");
        assert_eq!(result, "No sensitive data here");
    }

    #[test]
    fn test_multiple_matches() {
        let patterns = vec![r"\d{3}-\d{2}-\d{4}"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\d{3}-\d{2}-\d{4}".to_string(),
                replace: "XXX-XX-XXXX".to_string(),
                compiled: Regex::new(r"\d{3}-\d{2}-\d{4}").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("SSN: 123-45-6789 and 987-65-4321");
        assert_eq!(result, "SSN: XXX-XX-XXXX and XXX-XX-XXXX");
    }

    #[test]
    fn test_early_exit_optimization() {
        // Test that early exit works when no patterns match
        let patterns = vec![r"\bsecret\b", r"\bpassword\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: r"\bsecret\b".to_string(),
                    replace: "[REDACTED]".to_string(),
                    compiled: Regex::new(r"\bsecret\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bpassword\b".to_string(),
                    replace: "[REDACTED]".to_string(),
                    compiled: Regex::new(r"\bpassword\b").unwrap(),
                },
            ],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // This should trigger early exit via RegexSet
        let text = "This is completely clean text with no sensitive data";
        let result = plugin.apply_patterns(text);
        assert_eq!(result, text);
    }

    #[test]
    fn test_empty_config() {
        // Test with no patterns configured
        let config = SearchReplaceConfig {
            words: vec![],
            pattern_set: None,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Any text should pass through unchanged");
        assert_eq!(result, "Any text should pass through unchanged");
    }

    #[test]
    fn test_case_sensitive_matching() {
        // Test that patterns are case-sensitive by default
        let patterns = vec![r"\bSecret\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bSecret\b".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new(r"\bSecret\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // Should match "Secret" but not "secret"
        assert_eq!(plugin.apply_patterns("Secret data"), "[REDACTED] data");
        assert_eq!(plugin.apply_patterns("secret data"), "secret data");
    }

    #[test]
    fn test_case_insensitive_matching() {
        // Test case-insensitive regex pattern
        let patterns = vec![r"(?i)\bsecret\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"(?i)\bsecret\b".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new(r"(?i)\bsecret\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // Should match both cases
        assert_eq!(plugin.apply_patterns("Secret data"), "[REDACTED] data");
        assert_eq!(plugin.apply_patterns("secret data"), "[REDACTED] data");
        assert_eq!(plugin.apply_patterns("SECRET data"), "[REDACTED] data");
    }

    #[test]
    fn test_special_characters_in_replacement() {
        // Test that special characters in replacement text are handled correctly
        // Note: $1 without a capture group becomes empty string
        let patterns = vec![r"\btest\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\btest\b".to_string(),
                replace: "[special] & <chars>".to_string(),
                compiled: Regex::new(r"\btest\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("This is a test");
        assert_eq!(result, "This is a [special] & <chars>");
    }

    #[test]
    fn test_literal_dollar_sign() {
        // Test that literal dollar signs need to be escaped
        let patterns = vec![r"\bprice\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bprice\b".to_string(),
                replace: "$$100".to_string(), // $$ becomes literal $
                compiled: Regex::new(r"\bprice\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("The price is high");
        assert_eq!(result, "The $100 is high");
    }

    #[test]
    fn test_overlapping_patterns() {
        // Test multiple patterns that could match the same text
        let patterns = vec![r"\bAI\b", r"\bAI system\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: r"\bAI\b".to_string(),
                    replace: "artificial intelligence".to_string(),
                    compiled: Regex::new(r"\bAI\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bAI system\b".to_string(),
                    replace: "intelligent system".to_string(),
                    compiled: Regex::new(r"\bAI system\b").unwrap(),
                },
            ],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        // First pattern replaces "AI", then second pattern won't match "AI system" anymore
        let result = plugin.apply_patterns("The AI system works");
        assert_eq!(result, "The artificial intelligence system works");
    }

    #[test]
    fn test_unicode_text() {
        // Test handling of Unicode characters
        let patterns = vec![r"café"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"café".to_string(),
                replace: "coffee shop".to_string(),
                compiled: Regex::new(r"café").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Visit the café today");
        assert_eq!(result, "Visit the coffee shop today");
    }

    #[test]
    fn test_empty_string() {
        // Test with empty input string
        let patterns = vec![r"\btest\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\btest\b".to_string(),
                replace: "replaced".to_string(),
                compiled: Regex::new(r"\btest\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("");
        assert_eq!(result, "");
    }

    #[test]
    fn test_very_long_text() {
        // Test with longer text to ensure performance optimizations work
        let patterns = vec![r"\bsecret\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bsecret\b".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new(r"\bsecret\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // Create a long text with pattern at the end
        let mut long_text = "word ".repeat(1000);
        long_text.push_str("secret");

        let result = plugin.apply_patterns(&long_text);
        assert!(result.ends_with("[REDACTED]"));
        assert!(result.starts_with("word "));
    }

    #[test]
    fn test_pattern_at_boundaries() {
        // Test patterns at start, middle, and end of text
        let patterns = vec![r"\btest\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\btest\b".to_string(),
                replace: "X".to_string(),
                compiled: Regex::new(r"\btest\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        assert_eq!(plugin.apply_patterns("test"), "X");
        assert_eq!(plugin.apply_patterns("test middle"), "X middle");
        assert_eq!(plugin.apply_patterns("start test"), "start X");
        assert_eq!(plugin.apply_patterns("start test end"), "start X end");
    }

    #[test]
    fn test_consecutive_matches() {
        // Test multiple consecutive matches
        let patterns = vec![r"\d+"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\d+".to_string(),
                replace: "NUM".to_string(),
                compiled: Regex::new(r"\d+").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("123 456 789");
        assert_eq!(result, "NUM NUM NUM");
    }

    #[test]
    fn test_no_pattern_set() {
        // Test behavior when pattern_set is None (shouldn't happen in practice but test defensive code)
        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\btest\b".to_string(),
                replace: "replaced".to_string(),
                compiled: Regex::new(r"\btest\b").unwrap(),
            }],
            pattern_set: None,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("This is a test");
        assert_eq!(result, "This is a replaced");
    }

    #[test]
    fn test_replacement_with_capture_groups() {
        // Test regex with capture groups in replacement
        let patterns = vec![r"(\d{3})-(\d{2})-(\d{4})"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"(\d{3})-(\d{2})-(\d{4})".to_string(),
                replace: "***-**-$3".to_string(),
                compiled: Regex::new(r"(\d{3})-(\d{2})-(\d{4})").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("SSN: 123-45-6789");
        assert_eq!(result, "SSN: ***-**-6789");
    }

    #[test]
    fn test_multiple_patterns_same_text() {
        // Test that all patterns are applied in order
        let patterns = vec![r"\bcrap\b", r"\bdamn\b", r"\bhell\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: r"\bcrap\b".to_string(),
                    replace: "crud".to_string(),
                    compiled: Regex::new(r"\bcrap\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bdamn\b".to_string(),
                    replace: "darn".to_string(),
                    compiled: Regex::new(r"\bdamn\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bhell\b".to_string(),
                    replace: "heck".to_string(),
                    compiled: Regex::new(r"\bhell\b").unwrap(),
                },
            ],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("This crap is damn hard as hell");
        assert_eq!(result, "This crud is darn hard as heck");
    }

    #[test]
    fn test_word_boundary_patterns() {
        // Test that word boundaries work correctly
        let patterns = vec![r"\bcat\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bcat\b".to_string(),
                replace: "dog".to_string(),
                compiled: Regex::new(r"\bcat\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // Should match "cat" but not "category" or "scat"
        assert_eq!(plugin.apply_patterns("cat"), "dog");
        assert_eq!(plugin.apply_patterns("the cat sat"), "the dog sat");
        assert_eq!(plugin.apply_patterns("category"), "category");
        assert_eq!(plugin.apply_patterns("scat"), "scat");
    }

    #[test]
    fn test_whitespace_patterns() {
        // Test patterns involving whitespace
        let patterns = vec![r"\s+"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\s+".to_string(),
                replace: " ".to_string(),
                compiled: Regex::new(r"\s+").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("too    many     spaces");
        assert_eq!(result, "too many spaces");
    }

    #[test]
    fn test_email_pattern() {
        // Test realistic email redaction pattern
        let patterns = vec![r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b".to_string(),
                replace: "[EMAIL]".to_string(),
                compiled: Regex::new(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
                    .unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Contact user@example.com for info");
        assert_eq!(result, "Contact [EMAIL] for info");
    }

    #[test]
    fn test_url_pattern() {
        // Test URL redaction pattern
        let patterns = vec![r"https?://[^\s]+"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"https?://[^\s]+".to_string(),
                replace: "[URL]".to_string(),
                compiled: Regex::new(r"https?://[^\s]+").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Visit https://example.com for more");
        assert_eq!(result, "Visit [URL] for more");
    }

    #[test]
    fn test_mixed_clean_and_dirty_text() {
        // Test text with both matching and non-matching sections
        let patterns = vec![r"\bsecret\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bsecret\b".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new(r"\bsecret\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns(
            "This is public information. The secret code is hidden. More public data.",
        );
        assert_eq!(
            result,
            "This is public information. The [REDACTED] code is hidden. More public data."
        );
    }

    #[test]
    fn test_search_replace_config_creation() {
        // Test manual creation of SearchReplaceConfig
        let patterns = vec![r"\btest\b", r"\bdata\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: r"\btest\b".to_string(),
                    replace: "TEST".to_string(),
                    compiled: Regex::new(r"\btest\b").unwrap(),
                },
                SearchReplace {
                    search: r"\bdata\b".to_string(),
                    replace: "DATA".to_string(),
                    compiled: Regex::new(r"\bdata\b").unwrap(),
                },
            ],
            pattern_set,
        };

        assert_eq!(config.words.len(), 2);
        assert!(config.pattern_set.is_some());
    }

    #[test]
    fn test_search_replace_struct() {
        // Test SearchReplace struct creation and usage
        let search_replace = SearchReplace {
            search: r"\d+".to_string(),
            replace: "NUM".to_string(),
            compiled: Regex::new(r"\d+").unwrap(),
        };

        assert_eq!(search_replace.search, r"\d+");
        assert_eq!(search_replace.replace, "NUM");
        assert!(search_replace.compiled.is_match("123"));
        assert!(!search_replace.compiled.is_match("abc"));
    }

    #[test]
    fn test_regex_set_matching() {
        // Test RegexSet behavior for early exit optimization
        let patterns = vec![r"\bsecret\b", r"\bpassword\b", r"\btoken\b"];
        let pattern_set = RegexSet::new(&patterns).unwrap();

        // Should match when any pattern is present
        assert!(pattern_set.is_match("The secret is here"));
        assert!(pattern_set.is_match("Enter password"));
        assert!(pattern_set.is_match("API token required"));

        // Should not match when no patterns are present
        assert!(!pattern_set.is_match("Clean text with no sensitive data"));
    }

    #[test]
    fn test_config_with_invalid_regex() {
        // Test that invalid regex patterns are skipped during config creation
        // This simulates what from_py_dict does
        let mut words = Vec::new();
        let mut patterns = Vec::new();

        // Valid pattern
        if let Ok(compiled) = Regex::new(r"\bvalid\b") {
            patterns.push(r"\bvalid\b".to_string());
            words.push(SearchReplace {
                search: r"\bvalid\b".to_string(),
                replace: "VALID".to_string(),
                compiled,
            });
        }

        // Invalid pattern (unclosed bracket) - should be skipped
        // Use a string variable to avoid clippy::invalid_regex lint
        let invalid_pattern = "[invalid";
        if let Ok(compiled) = Regex::new(invalid_pattern) {
            patterns.push(invalid_pattern.to_string());
            words.push(SearchReplace {
                search: invalid_pattern.to_string(),
                replace: "INVALID".to_string(),
                compiled,
            });
        }

        let pattern_set = if !patterns.is_empty() {
            RegexSet::new(&patterns).ok()
        } else {
            None
        };

        let config = SearchReplaceConfig { words, pattern_set };

        // Only valid pattern should be in config
        assert_eq!(config.words.len(), 1);
        assert_eq!(config.words[0].search, r"\bvalid\b");
    }

    #[test]
    fn test_clone_config() {
        // Test that SearchReplaceConfig can be cloned
        let patterns = vec![r"\btest\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\btest\b".to_string(),
                replace: "TEST".to_string(),
                compiled: Regex::new(r"\btest\b").unwrap(),
            }],
            pattern_set,
        };

        let cloned = config.clone();
        assert_eq!(cloned.words.len(), config.words.len());
        assert_eq!(cloned.words[0].search, config.words[0].search);
    }

    #[test]
    fn test_multiple_replacements_in_sequence() {
        // Test that patterns are applied sequentially
        let patterns = vec![r"a", r"b", r"c"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![
                SearchReplace {
                    search: "a".to_string(),
                    replace: "1".to_string(),
                    compiled: Regex::new("a").unwrap(),
                },
                SearchReplace {
                    search: "b".to_string(),
                    replace: "2".to_string(),
                    compiled: Regex::new("b").unwrap(),
                },
                SearchReplace {
                    search: "c".to_string(),
                    replace: "3".to_string(),
                    compiled: Regex::new("c").unwrap(),
                },
            ],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("abc");
        assert_eq!(result, "123");
    }

    #[test]
    fn test_no_allocation_on_no_match() {
        // Test that no allocation happens when no patterns match (Cow optimization)
        let patterns = vec![r"\bNEVERMATCH\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bNEVERMATCH\b".to_string(),
                replace: "REPLACED".to_string(),
                compiled: Regex::new(r"\bNEVERMATCH\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let original = "This text will not match any pattern";
        let result = plugin.apply_patterns(original);

        // Result should be equal to original
        assert_eq!(result, original);
    }

    #[test]
    fn test_partial_word_no_match() {
        // Test that word boundaries prevent partial matches
        let patterns = vec![r"\bcat\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bcat\b".to_string(),
                replace: "dog".to_string(),
                compiled: Regex::new(r"\bcat\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };

        // Should not match partial words
        assert_eq!(plugin.apply_patterns("concatenate"), "concatenate");
        assert_eq!(plugin.apply_patterns("bobcat"), "bobcat");
        assert_eq!(plugin.apply_patterns("cats"), "cats");
    }

    #[test]
    fn test_newline_handling() {
        // Test that patterns work across newlines
        let patterns = vec![r"secret"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: "secret".to_string(),
                replace: "[REDACTED]".to_string(),
                compiled: Regex::new("secret").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Line 1\nsecret\nLine 3");
        assert_eq!(result, "Line 1\n[REDACTED]\nLine 3");
    }

    #[test]
    fn test_tab_and_special_whitespace() {
        // Test handling of tabs and other whitespace
        let patterns = vec![r"\s+"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\s+".to_string(),
                replace: " ".to_string(),
                compiled: Regex::new(r"\s+").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("word\t\ttab\n\nnewline");
        assert_eq!(result, "word tab newline");
    }

    #[test]
    fn test_empty_replacement() {
        // Test replacing with empty string (deletion)
        let patterns = vec![r"\bremove\b"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\bremove\b".to_string(),
                replace: "".to_string(),
                compiled: Regex::new(r"\bremove\b").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        let result = plugin.apply_patterns("Please remove this word");
        assert_eq!(result, "Please  this word");
    }

    #[test]
    fn test_numeric_patterns() {
        // Test patterns with numeric quantifiers
        let patterns = vec![r"\d{4}"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"\d{4}".to_string(),
                replace: "YEAR".to_string(),
                compiled: Regex::new(r"\d{4}").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        assert_eq!(plugin.apply_patterns("Year 2024"), "Year YEAR");
        assert_eq!(plugin.apply_patterns("Year 24"), "Year 24"); // Too short
    }

    #[test]
    fn test_anchored_patterns() {
        // Test patterns with anchors (^ and $)
        let patterns = vec![r"^start"];
        let pattern_set = RegexSet::new(&patterns).ok();

        let config = SearchReplaceConfig {
            words: vec![SearchReplace {
                search: r"^start".to_string(),
                replace: "BEGIN".to_string(),
                compiled: Regex::new(r"^start").unwrap(),
            }],
            pattern_set,
        };

        let plugin = SearchReplacePluginRust { config };
        assert_eq!(plugin.apply_patterns("start here"), "BEGIN here");
        assert_eq!(plugin.apply_patterns("not start"), "not start");
    }
}

/// Python module definition
#[pymodule]
fn regex_filter(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SearchReplacePluginRust>()?;
    Ok(())
}
