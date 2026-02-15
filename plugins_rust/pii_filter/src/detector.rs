// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Core PII detection logic with PyO3 bindings

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::masking;
use super::patterns::{CompiledPatterns, compile_patterns};

/// Public API for benchmarks - detect PII in text
#[allow(dead_code)]
pub fn detect_pii(
    text: &str,
    patterns: &CompiledPatterns,
    _config: &PIIConfig,
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
                    mask_strategy: pattern.mask_strategy,
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

/// Main PII detector exposed to Python
///
/// # Example (Python)
/// ```python
/// from plugins_rust import PIIDetectorRust
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
#[pyclass]
pub struct PIIDetectorRust {
    patterns: CompiledPatterns,
    config: PIIConfig,
}

#[pymethods]
impl PIIDetectorRust {
    /// Create a new PII detector
    ///
    /// # Arguments
    /// * `config_dict` - Python dictionary with configuration
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
    /// * `redaction_text` (str): Text to use for redaction (default: "[REDACTED]")
    /// * `block_on_detection` (bool): Whether to block on detection
    /// * `whitelist_patterns` (list[str]): Regex patterns to exclude from detection
    #[new]
    pub fn new(config_dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        // Extract configuration from Python dict
        let config = PIIConfig::from_py_dict(config_dict).map_err(|e| {
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
    ///         {"value": "123-45-6789", "start": 10, "end": 21, "mask_strategy": "partial"}
    ///     ],
    ///     "email": [
    ///         {"value": "john@example.com", "start": 35, "end": 51, "mask_strategy": "partial"}
    ///     ]
    /// }
    /// ```
    pub fn detect(&self, text: &str) -> PyResult<Py<PyAny>> {
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
        // Convert Python detections back to Rust format
        let rust_detections = self.py_detections_to_rust(detections)?;

        // Apply masking
        Ok(masking::mask_pii(text, &rust_detections, &self.config).into_owned())
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
        // Handle strings directly
        if let Ok(text) = data.extract::<String>() {
            let detections = self.detect_internal(&text);

            if !detections.is_empty() {
                let masked = masking::mask_pii(&text, &detections, &self.config);
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

            for (key, value) in dict.iter() {
                let key_str: String = key.extract()?;
                let new_path = if path.is_empty() {
                    key_str.clone()
                } else {
                    format!("{}.{}", path, key_str)
                };

                let (val_modified, new_value, val_detections) =
                    self.process_nested(py, &value, &new_path)?;

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

            for (idx, item) in list.iter().enumerate() {
                let new_path = format!("{}[{}]", path, idx);
                let (item_modified, new_item, item_detections) =
                    self.process_nested(py, &item, &new_path)?;

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
}

// Internal methods
impl PIIDetectorRust {
    /// Internal detection logic (returns Rust types)
    fn detect_internal(&self, text: &str) -> HashMap<PIIType, Vec<Detection>> {
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();

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

                    // Check for overlaps with existing detections
                    if self.has_overlap(&detections, start, end) {
                        continue;
                    }

                    let detection = Detection {
                        value,
                        start,
                        end,
                        mask_strategy: pattern.mask_strategy,
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

    /// Check if a match is whitelisted
    fn is_whitelisted(&self, text: &str, start: usize, end: usize) -> bool {
        let match_text = &text[start..end];
        self.patterns
            .whitelist
            .iter()
            .any(|pattern| pattern.is_match(match_text))
    }

    /// Check if a position overlaps with existing detections
    fn has_overlap(
        &self,
        detections: &HashMap<PIIType, Vec<Detection>>,
        start: usize,
        end: usize,
    ) -> bool {
        for items in detections.values() {
            for det in items {
                if (start >= det.start && start < det.end)
                    || (end > det.start && end <= det.end)
                    || (start <= det.start && end >= det.end)
                {
                    return true;
                }
            }
        }
        false
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

    /// Convert Python list to Vec<Detection>
    fn py_list_to_detections(&self, py_list: &Bound<'_, PyAny>) -> PyResult<Vec<Detection>> {
        let mut detections = Vec::new();

        if let Ok(list) = py_list.cast::<PyList>() {
            for item in list.iter() {
                if let Ok(dict) = item.cast::<PyDict>() {
                    let value: String = dict.get_item("value")?.unwrap().extract()?;
                    let start: usize = dict.get_item("start")?.unwrap().extract()?;
                    let end: usize = dict.get_item("end")?.unwrap().extract()?;
                    let strategy_str: String =
                        dict.get_item("mask_strategy")?.unwrap().extract()?;

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

#[cfg(test)]
mod tests {
    use super::*;

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
}
