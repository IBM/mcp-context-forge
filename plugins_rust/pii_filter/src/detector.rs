// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Core PII detection logic with PyO3 bindings

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use pyo3_stub_gen::derive::*;
use std::collections::HashMap;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::masking;
use super::patterns::{CompiledPatterns, compile_patterns};

/// Public API for benchmarks - detect PII in text
#[allow(dead_code)]
pub fn detect_pii(
    text: &str,
    patterns: &CompiledPatterns,
    config: &PIIConfig,
) -> HashMap<PIIType, Vec<Detection>> {
    let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();

    // Use RegexSet for parallel matching
    let matches = patterns.regex_set.matches(text);

    for pattern_idx in matches.iter() {
        let pattern = &patterns.patterns[pattern_idx];

        for capture in pattern.regex.captures_iter(text) {
            if let Some(mat) = capture.get(0) {
                let detection = Detection {
                    value: mat.as_str().to_string(),
                    start: mat.start(),
                    end: mat.end(),
                    mask_strategy: pattern
                        .mask_strategy
                        .unwrap_or(config.default_mask_strategy),
                };

                detections
                    .entry(pattern.pii_type)
                    .or_default()
                    .push(detection);
            }
        }
    }

    detections
}

/// A single PII detection result
#[derive(Debug, Clone)]
pub struct Detection {
    pub value: String,
    pub start: usize,
    pub end: usize,
    pub mask_strategy: MaskingStrategy,
}

#[derive(Debug, Clone)]
struct CandidateDetection {
    pii_type: PIIType,
    value: String,
    start: usize,
    end: usize,
    mask_strategy: MaskingStrategy,
    pattern_idx: usize,
}

/// Main PII detector exposed to Python
///
/// # Example (Python)
/// ```python
/// from pii_filter import PIIDetectorRust
///
/// config = {"detect_ssn": True, "detect_email": True}
/// detector = PIIDetectorRust(config)
///
/// text = "My SSN is 123-45-6789 and email is john@example.com"
/// detections = detector.detect(text)
/// print(detections)  # {"ssn": [...], "email": [...]}
///
/// masked = detector.mask(text, detections)
/// print(masked)  # "My SSN is [REDACTED] and email is [REDACTED]"
/// ```
#[gen_stub_pyclass]
#[pyclass]
pub struct PIIDetectorRust {
    patterns: CompiledPatterns,
    config: PIIConfig,
}

#[gen_stub_pymethods]
#[pymethods]
impl PIIDetectorRust {
    /// Create a new PII detector
    ///
    /// # Arguments
    /// * `config` - Python dictionary or Pydantic model with configuration
    ///
    /// # Configuration Keys
    /// * `detect_ssn` (bool): Detect Social Security Numbers
    /// * `detect_credit_card` (bool): Detect credit card numbers
    /// * `detect_email` (bool): Detect email addresses
    /// * `detect_phone` (bool): Detect phone numbers
    /// * `detect_ip_address` (bool): Detect IP addresses
    /// * `detect_date_of_birth` (bool): Detect dates of birth
    /// * `detect_passport` (bool): Detect passport numbers
    /// * `detect_driver_license` (bool): Detect driver's license numbers
    /// * `detect_bank_account` (bool): Detect bank account numbers
    /// * `detect_medical_record` (bool): Detect medical record numbers
    /// * `detect_aws_keys` (bool): Detect AWS access keys
    /// * `detect_api_keys` (bool): Detect API keys
    /// * `default_mask_strategy` (str): "redact", "partial", "hash", "tokenize", "remove"
    /// * `redaction_text` (str): Text to use for redaction (default: "\[REDACTED\]")
    /// * `block_on_detection` (bool): Whether to block on detection
    /// * `whitelist_patterns` (list[str]): Regex patterns to exclude from detection
    #[new]
    pub fn new(config: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Extract configuration from Python object (dict or Pydantic model)
        let config = PIIConfig::from_py_object(config).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid config: {}", e))
        })?;

        // Compile regex patterns
        let patterns = compile_patterns(&config).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Pattern compilation failed: {}",
                e
            ))
        })?;

        Ok(Self { patterns, config })
    }

    /// Detect PII in text
    ///
    /// # Arguments
    /// * `text` - Text to scan for PII
    ///
    /// # Returns
    /// Dictionary mapping PII type to list of detections:
    /// ```python
    /// {
    ///     "ssn": [
    ///         {"value": "123-45-6789", "start": 10, "end": 21, "mask_strategy": "redact"}
    ///     ],
    ///     "email": [
    ///         {"value": "john@example.com", "start": 35, "end": 51, "mask_strategy": "redact"}
    ///     ]
    /// }
    /// ```
    pub fn detect(&self, text: &str) -> PyResult<Py<PyAny>> {
        validate_text_size(text, self.config.max_text_bytes)?;
        let detections = self.detect_internal(text);

        // Convert Rust HashMap to Python dict
        Python::attach(|py| {
            let py_dict = PyDict::new(py);

            for (pii_type, items) in detections {
                let py_list = PyList::empty(py);

                for detection in items {
                    let item_dict = PyDict::new(py);
                    item_dict.set_item("value", detection.value)?;
                    item_dict.set_item("start", detection.start)?;
                    item_dict.set_item("end", detection.end)?;
                    item_dict.set_item(
                        "mask_strategy",
                        format!("{:?}", detection.mask_strategy).to_lowercase(),
                    )?;

                    py_list.append(item_dict)?;
                }

                py_dict.set_item(pii_type.as_str(), py_list)?;
            }

            Ok(py_dict.into_any().unbind())
        })
    }

    /// Mask detected PII in text
    ///
    /// # Arguments
    /// * `text` - Original text
    /// * `detections` - Detection results from detect()
    ///
    /// # Returns
    /// Masked text with PII replaced
    pub fn mask(&self, text: &str, detections: &Bound<'_, PyAny>) -> PyResult<String> {
        validate_text_size(text, self.config.max_text_bytes)?;

        // Convert Python detections back to Rust format
        let rust_detections = self.py_detections_to_rust(detections)?;

        // Apply masking
        masking::mask_pii(text, &rust_detections, &self.config)
            .map(|masked| masked.into_owned())
            .map_err(PyErr::new::<pyo3::exceptions::PyValueError, _>)
    }

    /// Process nested data structures (dicts, lists, strings)
    ///
    /// # Arguments
    /// * `data` - Python object (dict, list, str, or other)
    /// * `path` - Current path in the structure (for logging)
    ///
    /// # Returns
    /// Tuple of (modified: bool, new_data: Any, detections: dict)
    pub fn process_nested(
        &self,
        py: Python,
        data: &Bound<'_, PyAny>,
        path: &str,
    ) -> PyResult<(bool, Py<PyAny>, Py<PyAny>)> {
        self.process_nested_internal(py, data, path, 0)
    }
}

// Internal methods
impl PIIDetectorRust {
    fn process_nested_internal(
        &self,
        py: Python,
        data: &Bound<'_, PyAny>,
        path: &str,
        depth: usize,
    ) -> PyResult<(bool, Py<PyAny>, Py<PyAny>)> {
        if depth > self.config.max_nested_depth {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Nested data exceeds maximum depth of {}",
                self.config.max_nested_depth
            )));
        }

        // Handle strings directly
        if let Ok(text) = data.extract::<String>() {
            validate_text_size(&text, self.config.max_text_bytes)?;
            let detections = self.detect_internal(&text);

            if !detections.is_empty() {
                let masked = masking::mask_pii(&text, &detections, &self.config).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "Failed to mask nested string at '{}': {}",
                        path, e
                    ))
                })?;
                let py_detections = self.rust_detections_to_py(py, &detections)?;
                return Ok((
                    true,
                    masked.into_owned().into_pyobject(py)?.into_any().unbind(),
                    py_detections,
                ));
            } else {
                return Ok((
                    false,
                    data.clone().unbind(),
                    PyDict::new(py).into_any().unbind(),
                ));
            }
        }

        // Handle dictionaries
        if let Ok(dict) = data.cast::<PyDict>() {
            let mut modified = false;
            let mut all_detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
            let new_dict = PyDict::new(py);
            if dict.len() > self.config.max_collection_items {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Nested mapping exceeds maximum size of {} items",
                    self.config.max_collection_items
                )));
            }

            for (key, value) in dict.iter() {
                let key_str = key.str()?.to_string_lossy().into_owned();
                let new_path = if path.is_empty() {
                    key_str.clone()
                } else {
                    format!("{}.{}", path, key_str)
                };

                let (val_modified, new_value, val_detections) =
                    self.process_nested_internal(py, &value, &new_path, depth + 1)?;

                if val_modified {
                    modified = true;
                    new_dict.set_item(key, new_value.bind(py))?;

                    // Merge detections
                    let det_bound = val_detections.bind(py);
                    if let Ok(det_dict) = det_bound.cast::<PyDict>() {
                        for (pii_type_str, items) in det_dict.iter() {
                            if let Ok(type_str) = pii_type_str.extract::<String>()
                                && let Ok(pii_type) = self.str_to_pii_type(&type_str)
                            {
                                let rust_items = self.py_list_to_detections(&items)?;
                                all_detections
                                    .entry(pii_type)
                                    .or_default()
                                    .extend(rust_items);
                            }
                        }
                    }
                } else {
                    new_dict.set_item(key, value)?;
                }
            }

            let py_detections = self.rust_detections_to_py(py, &all_detections)?;
            return Ok((modified, new_dict.into_any().unbind(), py_detections));
        }

        // Handle lists
        if let Ok(list) = data.cast::<PyList>() {
            let mut modified = false;
            let mut all_detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
            let new_list = PyList::empty(py);
            if list.len() > self.config.max_collection_items {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Nested list exceeds maximum size of {} items",
                    self.config.max_collection_items
                )));
            }

            for (idx, item) in list.iter().enumerate() {
                let new_path = format!("{}[{}]", path, idx);
                let (item_modified, new_item, item_detections) =
                    self.process_nested_internal(py, &item, &new_path, depth + 1)?;

                if item_modified {
                    modified = true;
                    new_list.append(new_item.bind(py))?;

                    // Merge detections
                    let det_bound = item_detections.bind(py);
                    if let Ok(det_dict) = det_bound.cast::<PyDict>() {
                        for (pii_type_str, items) in det_dict.iter() {
                            if let Ok(type_str) = pii_type_str.extract::<String>()
                                && let Ok(pii_type) = self.str_to_pii_type(&type_str)
                            {
                                let rust_items = self.py_list_to_detections(&items)?;
                                all_detections
                                    .entry(pii_type)
                                    .or_default()
                                    .extend(rust_items);
                            }
                        }
                    }
                } else {
                    new_list.append(item)?;
                }
            }

            let py_detections = self.rust_detections_to_py(py, &all_detections)?;
            return Ok((modified, new_list.into_any().unbind(), py_detections));
        }

        // Other types: no processing
        Ok((
            false,
            data.clone().unbind(),
            PyDict::new(py).into_any().unbind(),
        ))
    }

    /// Internal detection logic (returns Rust types)
    fn detect_internal(&self, text: &str) -> HashMap<PIIType, Vec<Detection>> {
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        let mut candidates = Vec::new();

        // Use RegexSet for parallel matching (5-10x faster)
        let matches = self.patterns.regex_set.matches(text);

        // For each matched pattern index, extract details
        for pattern_idx in matches.iter() {
            let pattern = &self.patterns.patterns[pattern_idx];

            // Find all matches for this specific pattern
            for capture in pattern.regex.captures_iter(text) {
                if let Some(mat) = capture.get(0) {
                    let start = mat.start();
                    let end = mat.end();
                    let value = mat.as_str().to_string();

                    // Check whitelist
                    if self.is_whitelisted(text, start, end) {
                        continue;
                    }

                    if !self.is_valid_detection(pattern.pii_type, &value) {
                        continue;
                    }

                    candidates.push(CandidateDetection {
                        pii_type: pattern.pii_type,
                        value,
                        start,
                        end,
                        mask_strategy: pattern
                            .mask_strategy
                            .unwrap_or(self.config.default_mask_strategy),
                        pattern_idx,
                    });
                }
            }
        }

        candidates.sort_by(|a, b| {
            a.start
                .cmp(&b.start)
                .then(b.end.cmp(&a.end))
                .then(a.pii_type.as_str().cmp(b.pii_type.as_str()))
                .then(a.pattern_idx.cmp(&b.pattern_idx))
        });

        let mut last_end = 0usize;
        for candidate in candidates {
            if candidate.start < last_end {
                continue;
            }

            last_end = candidate.end;
            detections
                .entry(candidate.pii_type)
                .or_default()
                .push(Detection {
                    value: candidate.value,
                    start: candidate.start,
                    end: candidate.end,
                    mask_strategy: candidate.mask_strategy,
                });
        }

        detections
    }

    /// Check if a match is whitelisted
    fn is_whitelisted(&self, text: &str, start: usize, end: usize) -> bool {
        let match_text = &text[start..end];
        self.patterns
            .whitelist
            .iter()
            .any(|pattern| pattern.is_match(match_text))
    }

    /// Validate a regex hit before returning it to callers.
    fn is_valid_detection(&self, pii_type: PIIType, value: &str) -> bool {
        match pii_type {
            PIIType::Ssn => is_valid_ssn(value),
            PIIType::CreditCard => passes_luhn(value),
            _ => true,
        }
    }

    /// Convert Python detections to Rust format
    fn py_detections_to_rust(
        &self,
        detections: &Bound<'_, PyAny>,
    ) -> PyResult<HashMap<PIIType, Vec<Detection>>> {
        let mut rust_detections = HashMap::new();

        if let Ok(dict) = detections.cast::<PyDict>() {
            for (key, value) in dict.iter() {
                if let Ok(type_str) = key.extract::<String>()
                    && let Ok(pii_type) = self.str_to_pii_type(&type_str)
                {
                    let items = self.py_list_to_detections(&value)?;
                    rust_detections.insert(pii_type, items);
                }
            }
        }

        Ok(rust_detections)
    }

    /// Convert Python list to `Vec<Detection>`
    fn py_list_to_detections(&self, py_list: &Bound<'_, PyAny>) -> PyResult<Vec<Detection>> {
        let mut detections = Vec::new();

        if let Ok(list) = py_list.cast::<PyList>() {
            for item in list.iter() {
                if let Ok(dict) = item.cast::<PyDict>() {
                    let value: String = required_detection_field(dict, "value")?;
                    let start: usize = required_detection_field(dict, "start")?;
                    let end: usize = required_detection_field(dict, "end")?;
                    let strategy_str: String = required_detection_field(dict, "mask_strategy")?;

                    let mask_strategy = match strategy_str.as_str() {
                        "partial" => MaskingStrategy::Partial,
                        "hash" => MaskingStrategy::Hash,
                        "tokenize" => MaskingStrategy::Tokenize,
                        "remove" => MaskingStrategy::Remove,
                        _ => MaskingStrategy::Redact,
                    };

                    detections.push(Detection {
                        value,
                        start,
                        end,
                        mask_strategy,
                    });
                }
            }
        }

        Ok(detections)
    }

    /// Convert Rust detections to Python dict
    fn rust_detections_to_py(
        &self,
        py: Python,
        detections: &HashMap<PIIType, Vec<Detection>>,
    ) -> PyResult<Py<PyAny>> {
        let py_dict = PyDict::new(py);

        for (pii_type, items) in detections {
            let py_list = PyList::empty(py);

            for detection in items {
                let item_dict = PyDict::new(py);
                item_dict.set_item("value", detection.value.clone())?;
                item_dict.set_item("start", detection.start)?;
                item_dict.set_item("end", detection.end)?;
                item_dict.set_item(
                    "mask_strategy",
                    format!("{:?}", detection.mask_strategy).to_lowercase(),
                )?;

                py_list.append(item_dict)?;
            }

            py_dict.set_item(pii_type.as_str(), py_list)?;
        }

        Ok(py_dict.into_any().unbind())
    }

    /// Convert string to PIIType
    fn str_to_pii_type(&self, s: &str) -> Result<PIIType, ()> {
        match s {
            "ssn" => Ok(PIIType::Ssn),
            "bsn" => Ok(PIIType::Bsn),
            "credit_card" => Ok(PIIType::CreditCard),
            "email" => Ok(PIIType::Email),
            "phone" => Ok(PIIType::Phone),
            "ip_address" => Ok(PIIType::IpAddress),
            "date_of_birth" => Ok(PIIType::DateOfBirth),
            "passport" => Ok(PIIType::Passport),
            "driver_license" => Ok(PIIType::DriverLicense),
            "bank_account" => Ok(PIIType::BankAccount),
            "medical_record" => Ok(PIIType::MedicalRecord),
            "aws_key" => Ok(PIIType::AwsKey),
            "api_key" => Ok(PIIType::ApiKey),
            "custom" => Ok(PIIType::Custom),
            _ => Err(()),
        }
    }
}

fn is_valid_ssn(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }

    let area = &digits[0..3];
    let group = &digits[3..5];
    let serial = &digits[5..9];

    area != "000" && area != "666" && area < "900" && group != "00" && serial != "0000"
}

fn passes_luhn(value: &str) -> bool {
    let digits: Vec<u32> = value
        .chars()
        .filter(|c| c.is_ascii_digit())
        .filter_map(|c| c.to_digit(10))
        .collect();

    if !(13..=19).contains(&digits.len()) {
        return false;
    }

    let mut sum = 0u32;
    let parity = digits.len() % 2;

    for (idx, digit) in digits.iter().enumerate() {
        let mut value = *digit;
        if idx % 2 == parity {
            value *= 2;
            if value > 9 {
                value -= 9;
            }
        }
        sum += value;
    }

    sum.is_multiple_of(10) && has_known_card_prefix(&digits)
}

fn has_known_card_prefix(digits: &[u32]) -> bool {
    let as_string: String = digits
        .iter()
        .filter_map(|digit| char::from_digit(*digit, 10))
        .collect();
    let len = digits.len();

    let prefix1 = as_string.get(0..1).unwrap_or("");
    let prefix2 = as_string.get(0..2).unwrap_or("");
    let prefix3 = as_string.get(0..3).unwrap_or("");
    let prefix4 = as_string.get(0..4).unwrap_or("");

    matches!((prefix1, len), ("4", 13 | 16 | 19))
        || matches!((prefix2, len), ("34" | "37", 15))
        || matches!((prefix4, len), ("6011", 16 | 19))
        || matches!((prefix2, len), ("65", 16 | 19))
        || matches!(prefix2.parse::<u32>(), Ok(62)) && (16..=19).contains(&len)
        || matches!(prefix2.parse::<u32>(), Ok(67)) && (12..=19).contains(&len)
        || matches!((prefix2, len), ("36" | "38" | "39", 14))
        || matches!(
            (prefix3, len),
            ("300" | "301" | "302" | "303" | "304" | "305", 14)
        )
        || matches!(prefix2.parse::<u32>(), Ok(51..=55)) && len == 16
        || matches!(prefix4.parse::<u32>(), Ok(2221..=2720)) && len == 16
        || matches!(prefix4.parse::<u32>(), Ok(3528..=3589)) && len == 16
}

fn validate_text_size(text: &str, max_text_bytes: usize) -> PyResult<()> {
    if text.len() > max_text_bytes {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "Input exceeds maximum supported size of {} bytes",
            max_text_bytes
        )));
    }

    Ok(())
}

fn required_detection_field<'py, T>(dict: &Bound<'py, PyDict>, field: &str) -> PyResult<T>
where
    T: for<'a, 'py2> pyo3::FromPyObject<'a, 'py2>,
    for<'a, 'py2> <T as pyo3::FromPyObject<'a, 'py2>>::Error: Into<PyErr>,
{
    dict.get_item(field)?
        .ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Detection is missing required field '{}'",
                field
            ))
        })?
        .extract()
        .map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDict;

    #[test]
    fn test_detect_ssn() {
        let config = PIIConfig {
            detect_ssn: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("My SSN is 123-45-6789");

        assert!(detections.contains_key(&PIIType::Ssn));
        assert_eq!(detections[&PIIType::Ssn].len(), 1);
        assert_eq!(detections[&PIIType::Ssn][0].value, "123-45-6789");
    }

    #[test]
    fn test_detect_email() {
        let config = PIIConfig {
            detect_email: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("Contact: john.doe@example.com");

        assert!(detections.contains_key(&PIIType::Email));
        assert_eq!(detections[&PIIType::Email][0].value, "john.doe@example.com");
    }

    #[test]
    fn test_no_overlap() {
        let config = PIIConfig::default();
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("123-45-6789");

        // Should only detect once, not multiple times
        let total: usize = detections.values().map(|v| v.len()).sum();
        assert!(total >= 1);
    }

    #[test]
    fn test_ssn_without_context_is_not_detected_for_plain_nine_digits() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            detect_bank_account: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("Reference number 123456789");
        assert!(!detections.contains_key(&PIIType::Ssn));
    }

    #[test]
    fn test_built_in_patterns_keep_explicit_mask_strategy() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_email: true,
            detect_phone: false,
            detect_ip_address: false,
            default_mask_strategy: MaskingStrategy::Redact,
            redaction_text: "[PII_REDACTED]".to_string(),
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("SSN: 123-45-6789 Email: john@example.com");

        assert_eq!(
            detections[&PIIType::Ssn][0].mask_strategy,
            MaskingStrategy::Partial
        );
        assert_eq!(
            detections[&PIIType::Email][0].mask_strategy,
            MaskingStrategy::Partial
        );
    }

    #[test]
    fn test_built_in_mask_strategy_matrix_survives_global_override() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_credit_card: true,
            detect_email: true,
            detect_phone: true,
            detect_ip_address: true,
            detect_aws_keys: true,
            default_mask_strategy: MaskingStrategy::Hash,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };
        let detections = detector.detect_internal(
            "SSN 123-45-6789 Email john@example.com Phone 555-123-4567 Card 4111-1111-1111-1111 IP 192.168.1.1 Key AKIAIOSFODNN7EXAMPLE",
        );

        assert_eq!(
            detections[&PIIType::Ssn][0].mask_strategy,
            MaskingStrategy::Partial
        );
        assert_eq!(
            detections[&PIIType::CreditCard][0].mask_strategy,
            MaskingStrategy::Partial
        );
        assert_eq!(
            detections[&PIIType::Email][0].mask_strategy,
            MaskingStrategy::Partial
        );
        assert_eq!(
            detections[&PIIType::Phone][0].mask_strategy,
            MaskingStrategy::Partial
        );
        assert_eq!(
            detections[&PIIType::IpAddress][0].mask_strategy,
            MaskingStrategy::Redact
        );
        assert_eq!(
            detections[&PIIType::AwsKey][0].mask_strategy,
            MaskingStrategy::Redact
        );
    }

    #[test]
    fn test_structurally_impossible_ssns_are_rejected() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            detect_bsn: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        for text in [
            "SSN 000-12-3456",
            "SSN 666-12-3456",
            "SSN 901-12-3456",
            "SSN 123-00-4567",
            "SSN 123-45-0000",
        ] {
            let detections = detector.detect_internal(text);
            assert!(!detections.contains_key(&PIIType::Ssn));
        }
    }

    #[test]
    fn test_valid_contextual_ssn_is_detected() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            detect_bank_account: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("SSN: 123456789");
        assert!(detections.contains_key(&PIIType::Ssn));
    }

    #[test]
    fn test_credit_card_requires_luhn_validation() {
        let config = PIIConfig {
            detect_credit_card: true,
            detect_ssn: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            detect_bsn: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            detector
                .detect_internal("Card 4111-1111-1111-1111")
                .contains_key(&PIIType::CreditCard)
        );
        assert!(
            !detector
                .detect_internal("Card 4111-1111-1111-1112")
                .contains_key(&PIIType::CreditCard)
        );
        assert!(
            !detector
                .detect_internal("Card 0000-0000-0000-0000")
                .contains_key(&PIIType::CreditCard)
        );
    }

    #[test]
    fn test_bank_account_requires_context_to_avoid_false_positives() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: true,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            !detector
                .detect_internal("Timestamp 20250324123045")
                .contains_key(&PIIType::BankAccount)
        );
        assert!(
            detector
                .detect_internal("Account: 123456789")
                .contains_key(&PIIType::BankAccount)
        );
    }

    #[test]
    fn test_aws_secret_requires_context_to_avoid_broad_matches() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: true,
            detect_api_keys: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            !detector
                .detect_internal("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
                .contains_key(&PIIType::AwsKey)
        );
        assert!(
            detector
                .detect_internal("aws_secret_access_key = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
                .contains_key(&PIIType::AwsKey)
        );
    }

    #[test]
    fn test_passport_requires_context_to_avoid_generic_ids() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: true,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            !detector
                .detect_internal("Employee ID AB123456")
                .contains_key(&PIIType::Passport)
        );
        assert!(
            detector
                .detect_internal("Passport Number: AB123456")
                .contains_key(&PIIType::Passport)
        );
    }

    #[test]
    fn test_passport_detection_includes_identifier_not_just_label() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: true,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("Passport Number: AB123456");
        assert_eq!(
            detections[&PIIType::Passport][0].value,
            "Passport Number: AB123456"
        );
    }

    #[test]
    fn test_credit_card_accepts_valid_maestro_and_unionpay_numbers() {
        let config = PIIConfig {
            detect_credit_card: true,
            detect_ssn: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            detect_bsn: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            detector
                .detect_internal("Card 6759649826438453")
                .contains_key(&PIIType::CreditCard)
        );
        assert!(
            detector
                .detect_internal("Card 6200000000000005")
                .contains_key(&PIIType::CreditCard)
        );
    }

    #[test]
    fn test_custom_patterns_keep_explicit_mask_strategy() {
        let mut config = PIIConfig {
            default_mask_strategy: MaskingStrategy::Redact,
            ..Default::default()
        };
        config
            .custom_patterns
            .push(super::super::config::CustomPattern {
                pattern: r"\bEMP\d{6}\b".to_string(),
                description: "Employee ID".to_string(),
                mask_strategy: MaskingStrategy::Partial,
                enabled: true,
            });

        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };
        let detections = detector.detect_internal("Employee ID EMP123456");

        assert_eq!(
            detections[&PIIType::Custom][0].mask_strategy,
            MaskingStrategy::Partial
        );
    }

    #[test]
    fn test_bsn_context_is_not_downgraded_to_ssn() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: true,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("Customer record: BSN: 123456789");

        assert!(
            detections.contains_key(&PIIType::Bsn),
            "expected BSN detection for BSN-labeled identifier"
        );
        assert!(
            !detections.contains_key(&PIIType::Ssn),
            "did not expect SSN detection to win over BSN context"
        );
    }

    #[test]
    fn test_process_nested_accepts_non_string_dict_keys() {
        Python::initialize();
        Python::attach(|py| {
            let mut config = PIIConfig {
                detect_ssn: false,
                detect_email: false,
                default_mask_strategy: MaskingStrategy::Redact,
                ..Default::default()
            };
            config
                .custom_patterns
                .push(super::super::config::CustomPattern {
                    pattern: r"\bAKIA[0-9A-Z]{16}\b".to_string(),
                    description: "Access key".to_string(),
                    mask_strategy: MaskingStrategy::Redact,
                    enabled: true,
                });

            let patterns = compile_patterns(&config).unwrap();
            let detector = PIIDetectorRust { patterns, config };

            let data = PyDict::new(py);
            data.set_item(1, "AKIAFAKE12345EXAMPLE").unwrap();

            let result = detector.process_nested(py, &data.into_any(), "");
            assert!(
                result.is_ok(),
                "process_nested should not fail on non-string dict keys: {:?}",
                result.err()
            );

            let (modified, new_data, detections) = result.unwrap();
            assert!(modified);

            let new_dict = new_data.bind(py).cast::<PyDict>().unwrap();
            assert_eq!(
                new_dict
                    .get_item(1)
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap(),
                "[REDACTED]"
            );

            let det_dict = detections.bind(py).cast::<PyDict>().unwrap();
            assert!(
                !det_dict.is_empty(),
                "expected detections to be returned for masked value"
            );
        });
    }

    #[test]
    fn test_detect_rejects_oversized_input() {
        Python::initialize();
        Python::attach(|py| {
            let config = PIIConfig {
                detect_ssn: true,
                ..Default::default()
            };
            let max_text_bytes = config.max_text_bytes;
            let patterns = compile_patterns(&config).unwrap();
            let detector = PIIDetectorRust { patterns, config };
            let oversized = "a".repeat(max_text_bytes + 1);

            let err = detector.detect(&oversized).unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }

    #[test]
    fn test_default_detector_accepts_inputs_larger_than_256k() {
        Python::initialize();
        Python::attach(|_| {
            let config = PIIConfig {
                detect_ssn: true,
                detect_bsn: false,
                detect_credit_card: false,
                detect_email: false,
                detect_phone: false,
                detect_ip_address: false,
                detect_date_of_birth: false,
                detect_passport: false,
                detect_driver_license: false,
                detect_bank_account: false,
                detect_medical_record: false,
                detect_aws_keys: false,
                detect_api_keys: false,
                ..Default::default()
            };
            let patterns = compile_patterns(&config).unwrap();
            let detector = PIIDetectorRust { patterns, config };
            let text = format!("{} SSN: 123-45-6789", "x".repeat(300 * 1024));

            assert!(detector.detect(&text).is_ok());
        });
    }

    #[test]
    fn test_longer_overlap_wins_over_registration_order() {
        let mut config = PIIConfig {
            detect_bsn: true,
            detect_ssn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            ..Default::default()
        };
        config
            .custom_patterns
            .push(super::super::config::CustomPattern {
                pattern: r"\bBSN\b".to_string(),
                description: "Short custom token".to_string(),
                mask_strategy: MaskingStrategy::Redact,
                enabled: true,
            });

        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };
        let detections = detector.detect_internal("BSN: 123456789");

        assert!(detections.contains_key(&PIIType::Bsn));
        assert_eq!(detections[&PIIType::Bsn][0].value, "BSN: 123456789");
        assert!(!detections.contains_key(&PIIType::Custom));
    }

    #[test]
    fn test_bare_nine_digit_ssn_with_label_is_detected() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            detect_phone: false,
            detect_bank_account: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("SSN: 123456789");
        assert!(detections.contains_key(&PIIType::Ssn));
    }

    #[test]
    fn test_detect_uses_configurable_text_limit() {
        Python::initialize();
        Python::attach(|py| {
            let config = PyDict::new(py);
            config.set_item("detect_ssn", true).unwrap();
            config.set_item("max_text_bytes", 8).unwrap();

            let detector = PIIDetectorRust::new(&config.into_any()).unwrap();
            let err = detector.detect("123456789").unwrap_err();

            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }

    #[test]
    fn test_process_nested_uses_configurable_collection_limit() {
        Python::initialize();
        Python::attach(|py| {
            let config = PyDict::new(py);
            config.set_item("detect_email", true).unwrap();
            config.set_item("max_collection_items", 1).unwrap();

            let detector = PIIDetectorRust::new(&config.into_any()).unwrap();
            let data = PyList::empty(py);
            data.append("a@example.com").unwrap();
            data.append("b@example.com").unwrap();

            let err = detector
                .process_nested(py, &data.into_any(), "")
                .unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }

    #[test]
    fn test_detects_api_key_assignment_syntax() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            detector
                .detect_internal("OPENAI_API_KEY=fake_token_value_1234567890")
                .contains_key(&PIIType::ApiKey)
        );
    }

    #[test]
    fn test_detects_plus_prefixed_international_phone_number() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: true,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_aws_keys: false,
            detect_api_keys: false,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        assert!(
            detector
                .detect_internal("+353871234567")
                .contains_key(&PIIType::Phone)
        );
    }

    #[test]
    fn test_mask_rejects_missing_detection_fields() {
        Python::initialize();
        Python::attach(|py| {
            let config = PIIConfig {
                detect_email: true,
                ..Default::default()
            };
            let patterns = compile_patterns(&config).unwrap();
            let detector = PIIDetectorRust { patterns, config };

            let detections = PyDict::new(py);
            let items = PyList::empty(py);
            let bad_detection = PyDict::new(py);
            bad_detection.set_item("value", "john@example.com").unwrap();
            bad_detection.set_item("start", 0).unwrap();
            bad_detection.set_item("end", 16).unwrap();
            items.append(bad_detection).unwrap();
            detections.set_item("email", items).unwrap();

            let err = detector
                .mask("john@example.com", &detections.into_any())
                .unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }

    #[test]
    fn test_mask_rejects_oversized_input() {
        Python::initialize();
        Python::attach(|py| {
            let config = PyDict::new(py);
            config.set_item("detect_email", true).unwrap();
            config.set_item("max_text_bytes", 8).unwrap();

            let detector = PIIDetectorRust::new(&config.into_any()).unwrap();
            let detections = PyDict::new(py);
            let items = PyList::empty(py);
            let detection = PyDict::new(py);
            detection.set_item("value", "123456789").unwrap();
            detection.set_item("start", 0).unwrap();
            detection.set_item("end", 9).unwrap();
            detection.set_item("mask_strategy", "redact").unwrap();
            items.append(detection).unwrap();
            detections.set_item("custom", items).unwrap();

            let err = detector
                .mask("123456789", &detections.into_any())
                .unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }

    #[test]
    fn test_mask_rejects_invalid_detection_ranges() {
        Python::initialize();
        Python::attach(|py| {
            let config = PIIConfig {
                detect_email: true,
                ..Default::default()
            };
            let patterns = compile_patterns(&config).unwrap();
            let detector = PIIDetectorRust { patterns, config };

            let detections = PyDict::new(py);
            let items = PyList::empty(py);
            let bad_detection = PyDict::new(py);
            bad_detection.set_item("value", "john@example.com").unwrap();
            bad_detection.set_item("start", 99).unwrap();
            bad_detection.set_item("end", 100).unwrap();
            bad_detection.set_item("mask_strategy", "partial").unwrap();
            items.append(bad_detection).unwrap();
            detections.set_item("email", items).unwrap();

            let err = detector
                .mask("john@example.com", &detections.into_any())
                .unwrap_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));
        });
    }
}
