// SPDX-License-Identifier: Apache-2.0
//! Core PII detection logic, Luhn/BSN validation, and PyO3 bindings for the Python API.

use log::{info, warn};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use pyo3_stub_gen::derive::*;
use pythonize::{depythonize, pythonize};
use rlibphonenumber::PHONE_NUMBER_UTIL;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::error::{BlockError, ConfigError, PIIFilterError};
use super::masking::{self, effective_mask_strategy, resolve_overlaps, validate_text_span};
use super::patterns::{CompiledPatterns, compile_patterns};
use crate::{log_boundary_error, sanitized_path_depth, sanitized_path_kind};

#[derive(Debug, Clone)]
struct Candidate {
    start: usize,
    end: usize,
    capture_priority: usize,
    pii_type: PIIType,
    mask_strategy: MaskingStrategy,
    value: String,
    description: String,
}

/// Public API for benchmarks and integration tests - detect PII in text
pub fn detect_pii(
    text: &str,
    patterns: &CompiledPatterns,
    config: &PIIConfig,
) -> HashMap<PIIType, Vec<Detection>> {
    detections_from_candidates(collect_candidates(text, patterns, config))
}

/// A single PII detection result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Detection {
    pub value: String,
    pub start: usize,
    pub end: usize,
    pub mask_strategy: MaskingStrategy,
    /// Human-readable pattern description (e.g. "US Social Security Number").
    pub description: String,
}

#[derive(Debug, Clone, Copy)]
struct UnknownPIIType<'a> {
    value: &'a str,
}

#[derive(Debug, PartialEq, Eq)]
struct DetectionLogFields {
    path_kind: &'static str,
    path_depth: usize,
    pii_types: String,
    detection_count: usize,
}

#[derive(Debug, Deserialize)]
struct PyDetectionInput {
    value: String,
    start: usize,
    end: usize,
    mask_strategy: String,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Serialize)]
struct PyDetectionOutput<'a> {
    value: &'a str,
    start: usize,
    end: usize,
    mask_strategy: MaskingStrategy,
    #[serde(skip_serializing_if = "Option::is_none")]
    description: Option<&'a str>,
}

/// Main PII detector exposed to Python
///
/// # Example (Python)
/// ```python
/// from pii_filter_rust import PIIDetectorRust
///
/// config = {"detect_ssn": True, "detect_email": True}
/// detector = PIIDetectorRust(config)
///
/// text = "My SSN is 123-45-6789 and email is john@example.com"
/// detections = detector.detect(text)  # {"ssn": [{"value": "123-45-6789", "start": 10, "end": 21, "mask_strategy": "partial", "description": "US Social Security Number"}], "email": [{"value": "john@example.com", "start": 35, "end": 51, "mask_strategy": "partial", "description": "Email address"}]}
/// masked: str = detector.mask(text, detections)  # "My SSN is ***-**-6789 and email is j***n@example.com"
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
    /// * `detect_credit_card` (bool): Detect credit card numbers (Luhn-validated)
    /// * `detect_email` (bool): Detect email addresses
    /// * `detect_phone` (bool): Detect libphonenumber-validated U.S. domestic formats and international numbers with country code
    /// * `detect_ip_address` (bool): Detect IPv4 and standard fully expanded or compressed IPv6 addresses
    /// * `detect_date_of_birth` (bool): Detect dates of birth with DOB or birth-date style context
    /// * `detect_passport` (bool): Detect U.S. (9 digits) and EU-style (2 letters + 7 digits) passport numbers with passport label or U.S. / EU region marker
    /// * `detect_driver_license` (bool): Detect driver license numbers for CA, TX, FL, and NY with driver-license label or state marker
    /// * `detect_bank_account` (bool): Detect contextual 8-17 digit bank account numbers and checksum-validated IBAN
    /// * `detect_medical_record` (bool): Detect contextual MRN / Medical Record identifiers
    /// * `detect_full_name` (bool): Detect labeled full names
    /// * `detect_street_address` (bool): Detect labeled street addresses with common English street suffixes
    /// * `detect_us_aba_routing_number` (bool): Detect 9-digit U.S. ABA routing transit numbers that satisfy prefix and checksum rules
    /// * `detect_us_zip_code` (bool): Detect labeled US ZIP codes
    /// * `detect_us_ein` (bool): Detect labeled U.S. employer identification numbers
    /// * `detect_us_itin` (bool): Detect labeled U.S. individual taxpayer identification numbers
    /// * `default_mask_strategy` (str): "auto" (alias: "default"), "redact", "partial", "hash", "tokenize", "remove"
    /// * `redaction_text` (str): Text to use for redaction (default: "\[REDACTED\]")
    /// * `block_on_detection` (bool): Whether to error instead of masking when PII is found
    /// * `log_detections` (bool): Whether to log detections to stderr
    /// * `include_detection_details` (bool): Whether to include descriptions in the Python detection payload
    /// * `whitelist_patterns` (list[str]): Regex patterns to exclude from detection
    #[new]
    pub fn new(config: &Bound<'_, PyAny>) -> PyResult<Self> {
        match Self::try_new(config) {
            Ok(detector) => Ok(detector),
            Err(err) => {
                log_boundary_error("new", &err);
                Err(err.to_py_err())
            }
        }
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
    pub fn detect(&self, py: Python<'_>, text: &str) -> PyResult<Py<PyAny>> {
        let detections = self.detect_internal(text);
        self.log_detections("detect", None, &detections);
        self.rust_detections_to_py(py, &detections)
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
        match self.try_mask(text, detections) {
            Ok(masked) => Ok(masked),
            Err(err) => {
                log_boundary_error("mask", &err);
                Err(err.to_py_err())
            }
        }
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
        match self.try_process_nested(py, data, path) {
            Ok(result) => Ok(result),
            Err(err) => {
                log_boundary_error("process_nested", &err);
                Err(err.to_py_err())
            }
        }
    }
}

// Typed boundary methods (converted to PyErr at pymethod boundary)
impl PIIDetectorRust {
    fn try_new(config: &Bound<'_, PyAny>) -> Result<Self, PIIFilterError> {
        let config = PIIConfig::try_from_py_object(config)?;
        let patterns = compile_patterns(&config)?;
        Ok(Self { patterns, config })
    }

    fn try_mask(
        &self,
        text: &str,
        detections: &Bound<'_, PyAny>,
    ) -> Result<String, PIIFilterError> {
        let rust_detections = self.py_detections_to_rust_typed(detections)?;
        self.block_if_configured(&rust_detections)?;
        Ok(masking::mask_pii(text, &rust_detections, &self.config)?.into_owned())
    }

    fn try_process_nested(
        &self,
        py: Python,
        data: &Bound<'_, PyAny>,
        path: &str,
    ) -> Result<(bool, Py<PyAny>, Py<PyAny>), PIIFilterError> {
        // Handle strings directly
        if let Ok(text) = data.extract::<String>() {
            let detections = self.detect_internal(&text);
            self.log_detections("process_nested", Some(path), &detections);

            if !detections.is_empty() {
                self.block_if_configured(&detections)?;
                let masked = masking::mask_pii(&text, &detections, &self.config)?;
                let py_detections = self.rust_detections_to_py(py, &detections)?;
                let py_string = match masked.into_owned().into_pyobject(py) {
                    Ok(value) => value.into_any().unbind(),
                    Err(never) => match never {},
                };
                return Ok((true, py_string, py_detections));
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
                let new_path = match key.extract::<String>() {
                    Ok(key_str) if path.is_empty() => key_str,
                    Ok(key_str) => format!("{}.{}", path, key_str),
                    Err(_) => path.to_string(),
                };

                let (val_modified, new_value, val_detections) =
                    self.try_process_nested(py, &value, &new_path)?;

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
                                let rust_items = self.py_list_to_detections_typed(&items)?;
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
                    self.try_process_nested(py, &item, &new_path)?;

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
                                let rust_items = self.py_list_to_detections_typed(&items)?;
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
        detections_from_candidates(collect_candidates(text, &self.patterns, &self.config))
    }

    /// Convert Python detections to Rust format (typed errors)
    fn py_detections_to_rust_typed(
        &self,
        detections: &Bound<'_, PyAny>,
    ) -> Result<HashMap<PIIType, Vec<Detection>>, PIIFilterError> {
        let mut rust_detections = HashMap::new();
        let dict: HashMap<String, Vec<PyDetectionInput>> =
            depythonize(detections).map_err(|e| ConfigError::InvalidField {
                field: "detections",
                details: e.to_string(),
            })?;

        for (type_str, value) in dict {
            let pii_type =
                self.str_to_pii_type(&type_str)
                    .map_err(|err| ConfigError::InvalidField {
                        field: "detections",
                        details: format!("unsupported PII type '{}'", err.value),
                    })?;
            let items = self.py_detection_inputs_to_rust(value)?;
            rust_detections.insert(pii_type, items);
        }

        Ok(rust_detections)
    }

    /// Convert Python list to `Vec<Detection>` (typed errors)
    fn py_list_to_detections_typed(
        &self,
        py_list: &Bound<'_, PyAny>,
    ) -> Result<Vec<Detection>, PIIFilterError> {
        let items: Vec<PyDetectionInput> =
            depythonize(py_list).map_err(|e| ConfigError::InvalidField {
                field: "detections",
                details: e.to_string(),
            })?;
        self.py_detection_inputs_to_rust(items)
    }

    fn py_detection_inputs_to_rust(
        &self,
        items: Vec<PyDetectionInput>,
    ) -> Result<Vec<Detection>, PIIFilterError> {
        let mut detections = Vec::new();

        for item in items {
            let mask_strategy =
                MaskingStrategy::parse(item.mask_strategy.as_str(), "detections.mask_strategy")?;
            validate_text_span(item.value.as_str(), 0, item.value.len())
                .map_err(PIIFilterError::from)?;
            if item.start >= item.end {
                return Err(ConfigError::InvalidField {
                    field: "detections",
                    details: format!(
                        "invalid detection span start={} end={}",
                        item.start, item.end
                    ),
                }
                .into());
            }

            detections.push(Detection {
                value: item.value,
                start: item.start,
                end: item.end,
                mask_strategy,
                description: item.description.unwrap_or_default(),
            });
        }

        Ok(detections)
    }

    /// Convert Rust detections to Python dict
    fn rust_detections_to_py(
        &self,
        py: Python,
        detections: &HashMap<PIIType, Vec<Detection>>,
    ) -> PyResult<Py<PyAny>> {
        let payload: HashMap<&str, Vec<PyDetectionOutput<'_>>> = detections
            .iter()
            .map(|(pii_type, items)| {
                (
                    pii_type.as_str(),
                    items
                        .iter()
                        .map(|detection| PyDetectionOutput {
                            value: detection.value.as_str(),
                            start: detection.start,
                            end: detection.end,
                            mask_strategy: detection.mask_strategy,
                            description: self
                                .config
                                .include_detection_details
                                .then_some(detection.description.as_str()),
                        })
                        .collect(),
                )
            })
            .collect();

        Ok(pythonize(py, &payload).map(|value| value.unbind())?)
    }

    /// Convert string to PIIType
    fn str_to_pii_type<'a>(&self, s: &'a str) -> Result<PIIType, UnknownPIIType<'a>> {
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
            "full_name" => Ok(PIIType::FullName),
            "street_address" => Ok(PIIType::StreetAddress),
            "us_aba_routing_number" => Ok(PIIType::UsAbaRoutingNumber),
            "us_zip_code" => Ok(PIIType::UsZipCode),
            "us_ein" => Ok(PIIType::UsEin),
            "us_itin" => Ok(PIIType::UsItin),
            "custom" => Ok(PIIType::Custom),
            _ => Err(UnknownPIIType { value: s }),
        }
    }

    fn block_if_configured(
        &self,
        detections: &HashMap<PIIType, Vec<Detection>>,
    ) -> Result<(), PIIFilterError> {
        if !self.config.block_on_detection || detections.is_empty() {
            return Ok(());
        }

        let count = detections.values().map(Vec::len).sum();
        let mut pii_types: Vec<&'static str> = detections.keys().map(PIIType::as_str).collect();
        pii_types.sort_unstable();
        let pii_types_csv = pii_types.join(",");
        warn!(
            "event=pii_filter_detection_blocked detection_count={count} pii_types={pii_types_csv} block_on_detection={}",
            self.config.block_on_detection,
        );
        Err(BlockError::DetectionBlocked {
            count,
            pii_types: pii_types.join(", "),
        }
        .into())
    }

    fn log_detections(
        &self,
        operation: &'static str,
        path: Option<&str>,
        detections: &HashMap<PIIType, Vec<Detection>>,
    ) {
        if !self.config.log_detections || detections.is_empty() {
            return;
        }

        let fields = detection_log_fields(path, detections);
        info!(
            "event=pii_filter_detection operation={operation} path_kind={} path_depth={} pii_types={} detection_count={} block_on_detection={}",
            fields.path_kind,
            fields.path_depth,
            fields.pii_types,
            fields.detection_count,
            self.config.block_on_detection,
        );
    }
}

fn detection_log_fields(
    path: Option<&str>,
    detections: &HashMap<PIIType, Vec<Detection>>,
) -> DetectionLogFields {
    let mut pii_types: Vec<&'static str> = detections.keys().map(PIIType::as_str).collect();
    pii_types.sort_unstable();

    DetectionLogFields {
        path_kind: sanitized_path_kind(path),
        path_depth: sanitized_path_depth(path),
        pii_types: pii_types.join(","),
        detection_count: detections.values().map(Vec::len).sum(),
    }
}

/// ISO/IEC 7812: card numbers are 12–19 digits.
const MIN_CC_DIGITS: u32 = 12;
const MAX_CC_DIGITS: u32 = 19;

fn collect_candidates(
    text: &str,
    patterns: &CompiledPatterns,
    config: &PIIConfig,
) -> Vec<Candidate> {
    let mut candidates = Vec::new();
    let matches = patterns.regex_set.matches(text);

    for pattern_idx in matches.iter() {
        let pattern = &patterns.patterns[pattern_idx];

        for capture in pattern.regex.captures_iter(text) {
            let mat = capture.get(1).or_else(|| capture.get(0));
            if let Some(mat) = mat {
                let value = mat.as_str();
                if patterns.whitelist.iter().any(|re| re.is_match(value)) {
                    continue;
                }
                if pattern.pii_type == PIIType::CreditCard && !passes_luhn(value) {
                    continue;
                }
                if pattern.pii_type == PIIType::Bsn && !passes_bsn_elfproef(value) {
                    continue;
                }
                if pattern.pii_type == PIIType::Ssn && !passes_ssn(value) {
                    continue;
                }
                if pattern.pii_type == PIIType::Phone && !passes_phone(value) {
                    continue;
                }
                if pattern.pii_type == PIIType::UsAbaRoutingNumber && !passes_aba_routing(value) {
                    continue;
                }
                if pattern.pii_type == PIIType::BankAccount
                    && is_potential_iban(value)
                    && !passes_iban(value)
                {
                    continue;
                }

                candidates.push(Candidate {
                    start: mat.start(),
                    end: mat.end(),
                    capture_priority: pattern.regex.captures_len(),
                    pii_type: pattern.pii_type,
                    mask_strategy: effective_mask_strategy(
                        pattern.pii_type,
                        pattern.mask_strategy,
                        config,
                    ),
                    value: value.to_string(),
                    description: pattern.description.clone(),
                });
            }
        }
    }

    resolve_overlaps(
        candidates,
        |candidate| candidate.start,
        |candidate| candidate.end,
        |replacement, incumbent| {
            let incumbent_len = incumbent.end - incumbent.start;
            let replacement_len = replacement.end - replacement.start;
            replacement_len > incumbent_len
                || (replacement_len == incumbent_len
                    && replacement.capture_priority > incumbent.capture_priority)
        },
    )
}

fn detections_from_candidates(candidates: Vec<Candidate>) -> HashMap<PIIType, Vec<Detection>> {
    let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
    for candidate in candidates {
        detections
            .entry(candidate.pii_type)
            .or_default()
            .push(Detection {
                value: candidate.value,
                start: candidate.start,
                end: candidate.end,
                mask_strategy: candidate.mask_strategy,
                description: candidate.description,
            });
    }
    detections
}

fn passes_luhn(value: &str) -> bool {
    let mut sum = 0u32;
    let mut digits = 0u32;
    let mut double = false;

    // Iterate right-to-left over digits only.
    for b in value.as_bytes().iter().rev() {
        if !b.is_ascii_digit() {
            continue;
        }
        let mut d = (b - b'0') as u32;
        digits += 1;
        if double {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        sum += d;
        double = !double;
    }

    (MIN_CC_DIGITS..=MAX_CC_DIGITS).contains(&digits) && sum % 10 == 0
}

fn passes_ssn(value: &str) -> bool {
    let digits: String = value.chars().filter(|ch| ch.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }

    let area = &digits[0..3];
    let group = &digits[3..5];
    let serial = &digits[5..9];

    area != "000" && area != "666" && !area.starts_with('9') && group != "00" && serial != "0000"
}

fn passes_phone(value: &str) -> bool {
    if value.trim_start().starts_with('+') {
        return PHONE_NUMBER_UTIL
            .parse(value)
            .map(|number| PHONE_NUMBER_UTIL.is_valid_number(&number))
            .unwrap_or(false);
    }

    PHONE_NUMBER_UTIL
        .parse_with_default_region(value, "US")
        .map(|number| PHONE_NUMBER_UTIL.is_valid_number(&number))
        .unwrap_or(false)
}

fn is_potential_iban(value: &str) -> bool {
    let compact: String = value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .collect();
    compact.len() >= 15
        && compact.len() <= 34
        && compact.chars().take(2).all(|ch| ch.is_ascii_alphabetic())
        && compact.chars().nth(2).is_some_and(|ch| ch.is_ascii_digit())
        && compact.chars().nth(3).is_some_and(|ch| ch.is_ascii_digit())
}

fn passes_iban(value: &str) -> bool {
    let compact = value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .map(|ch| ch.to_ascii_uppercase())
        .collect::<String>();

    if !is_potential_iban(&compact) {
        return false;
    }

    let rearranged = format!("{}{}", &compact[4..], &compact[..4]);
    let mut remainder = 0u32;

    for ch in rearranged.chars() {
        if ch.is_ascii_digit() {
            remainder = (remainder * 10 + ch.to_digit(10).unwrap_or(0)) % 97;
        } else if ch.is_ascii_uppercase() {
            let numeric = 10 + (ch as u32 - 'A' as u32);
            remainder = (remainder * 100 + numeric) % 97;
        } else {
            return false;
        }
    }

    remainder == 1
}

fn passes_aba_routing(value: &str) -> bool {
    let digits: Vec<u32> = value
        .bytes()
        .filter(|b| b.is_ascii_digit())
        .map(|b| (b - b'0') as u32)
        .collect();
    if digits.len() != 9 {
        return false;
    }

    let prefix = digits[0] * 10 + digits[1];
    let valid_prefix = (1..=12).contains(&prefix)
        || (21..=32).contains(&prefix)
        || (61..=72).contains(&prefix)
        || prefix == 80;
    if !valid_prefix {
        return false;
    }

    let checksum = 3 * (digits[0] + digits[3] + digits[6])
        + 7 * (digits[1] + digits[4] + digits[7])
        + (digits[2] + digits[5] + digits[8]);
    checksum % 10 == 0
}

/// Dutch BSN (Burgerservicenummer) 11-check (elfproef).
/// Weights: 9,8,7,6,5,4,3,2 for first 8 digits, -1 for last; sum must be divisible by 11.
/// Accepts 8 or 9 digits (leading zero implied for 8). Rejects all zeros.
fn passes_bsn_elfproef(value: &str) -> bool {
    let digits: Vec<u32> = value
        .bytes()
        .filter(|b| b.is_ascii_digit())
        .map(|b| (b - b'0') as u32)
        .collect();
    let n = digits.len();
    if n == 8 {
        // Leading zero implied (python-stdnum compact with zfill(9)): 0,d0..d7, weights 9,8,7..2,-1
        let sum: i32 = (0..7)
            .map(|i| (8 - i) as i32 * digits[i] as i32)
            .sum::<i32>()
            - digits[7] as i32;
        return sum % 11 == 0 && digits.iter().any(|&d| d != 0);
    }
    if n != 9 {
        return false;
    }
    // Weights 9,8,7,6,5,4,3,2 for indices 0..8, and -1 for index 8 (last digit).
    let sum: i32 = (0..8)
        .map(|i| (9 - i) as i32 * digits[i] as i32)
        .sum::<i32>()
        - digits[8] as i32;
    if sum % 11 != 0 {
        return false;
    }
    // Reject all zeros (000000000)
    digits.iter().any(|&d| d != 0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::ConfigError;
    use crate::error::PIIFilterError;
    use crate::init_logging;
    use std::sync::OnceLock;

    fn init_python() {
        static INIT: OnceLock<()> = OnceLock::new();
        INIT.get_or_init(|| {
            // This crate does not enable PyO3's auto-initialize in tests, so we
            // initialize the interpreter once for unit tests that construct
            // Python objects.
            unsafe {
                if pyo3::ffi::Py_IsInitialized() == 0 {
                    pyo3::ffi::Py_Initialize();
                }
            }
        });
    }

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
    fn test_detect_uses_explicit_default_mask_strategy_override() {
        let config = PIIConfig {
            detect_ssn: true,
            default_mask_strategy: MaskingStrategy::Redact,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("My SSN is 123-45-6789");

        assert_eq!(
            detections[&PIIType::Ssn][0].mask_strategy,
            MaskingStrategy::Redact
        );
    }

    #[test]
    fn test_detect_default_mode_keeps_reasonable_builtin_strategy() {
        let config = PIIConfig {
            detect_date_of_birth: true,
            default_mask_strategy: MaskingStrategy::Auto,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        let detections = detector.detect_internal("DOB: 01/15/1990");

        assert_eq!(
            detections[&PIIType::DateOfBirth][0].mask_strategy,
            MaskingStrategy::Redact
        );
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
    fn test_credit_card_requires_luhn() {
        let config = PIIConfig {
            detect_credit_card: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        // Valid Luhn (Visa test number)
        let ok = detector.detect_internal("card: 4111 1111 1111 1111");
        assert!(ok.contains_key(&PIIType::CreditCard));
        assert_eq!(ok[&PIIType::CreditCard][0].value, "4111 1111 1111 1111");

        // Same format, invalid checksum -> should not be detected.
        let bad = detector.detect_internal("card: 4111 1111 1111 1112");
        assert!(!bad.contains_key(&PIIType::CreditCard));
    }

    #[test]
    fn test_bsn_requires_elfproef() {
        let config = PIIConfig {
            detect_bsn: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        // Valid BSN (111222333: 9*1+8*1+7*1+6*2+5*2+4*2+3*3+2*3-3 = 9+8+7+12+10+8+9+6-3 = 66, 66%11=0)
        let ok = detector.detect_internal("BSN: 111222333");
        assert!(ok.contains_key(&PIIType::Bsn));
        assert_eq!(ok[&PIIType::Bsn][0].value, "111222333");

        // Valid BSN dotted format (python-stdnum example)
        let ok_dotted = detector.detect_internal("My BSN is 1112.22.333");
        assert!(ok_dotted.contains_key(&PIIType::Bsn));

        // Same format, invalid 11-check -> should not be detected
        let bad = detector.detect_internal("BSN: 111222334");
        assert!(!bad.contains_key(&PIIType::Bsn));
    }

    #[test]
    fn test_phone_requires_libphonenumber_validation() {
        assert!(passes_phone("+442083661177"));
        assert!(passes_phone("(650) 253-0000"));
        assert!(!passes_phone("123-456-7890"));
        assert!(!passes_phone("1111111"));
    }

    #[test]
    fn test_iban_requires_mod97_checksum() {
        assert!(passes_iban("DE89370400440532013000"));
        assert!(passes_iban("GB82WEST12345698765432"));
        assert!(!passes_iban("DE00370400440532013000"));
        assert!(!passes_iban("GB00WEST12345698765432"));
    }

    #[test]
    fn test_aba_routing_requires_checksum_and_valid_prefix() {
        assert!(passes_aba_routing("021000021"));
        assert!(passes_aba_routing("011000015"));
        assert!(!passes_aba_routing("121000022"));
        assert!(!passes_aba_routing("991000021"));
    }

    #[test]
    fn test_whitelist_excludes_match() {
        let config = PIIConfig {
            detect_ssn: true,
            whitelist_patterns: vec!["123-45-6789".to_string()],
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };
        let detections = detector.detect_internal("My SSN is 123-45-6789");
        assert!(!detections.contains_key(&PIIType::Ssn));
    }

    #[test]
    fn test_detect_pii_public_helper_matches_internal_logic() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_credit_card: true,
            detect_email: true,
            whitelist_patterns: vec!["john@example\\.com".to_string()],
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust {
            patterns: compile_patterns(&config).unwrap(),
            config: config.clone(),
        };
        let text = "SSN: 123-45-6789 email john@example.com cc 4111 1111 1111 1112";

        let public = detect_pii(text, &patterns, &config);
        let internal = detector.detect_internal(text);

        assert_eq!(public.len(), internal.len());
        assert_eq!(
            public[&PIIType::Ssn][0].value,
            internal[&PIIType::Ssn][0].value
        );
        assert!(!public.contains_key(&PIIType::Email));
        assert!(!public.contains_key(&PIIType::CreditCard));
    }

    /// Single test that uses Python::attach so we only attach once per process.
    #[test]
    fn test_python_api() {
        init_python();
        init_logging();
        let config = PIIConfig::default();
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };

        Python::attach(|py| {
            // --- PIIConfig::try_from_py_dict (moved from config.rs to avoid multiple attach)
            let dict = PyDict::new(py);
            dict.set_item("detect_ssn", false).unwrap();
            dict.set_item("redaction_text", "X").unwrap();
            dict.set_item("default_mask_strategy", "partial").unwrap();
            let cfg = PIIConfig::try_from_py_dict(&dict).unwrap();
            assert!(!cfg.detect_ssn);
            assert_eq!(cfg.redaction_text, "X");
            assert_eq!(cfg.default_mask_strategy, MaskingStrategy::Partial);

            let dict = PyDict::new(py);
            let patterns_list = PyList::empty(py);
            let item = PyDict::new(py);
            item.set_item("pattern", r"\b\d{5}\b").unwrap();
            item.set_item("description", "ZIP").unwrap();
            item.set_item("mask_strategy", "hash").unwrap();
            item.set_item("enabled", true).unwrap();
            patterns_list.append(item).unwrap();
            dict.set_item("custom_patterns", patterns_list).unwrap();
            let cfg = PIIConfig::try_from_py_dict(&dict).unwrap();
            assert_eq!(cfg.custom_patterns.len(), 1);
            assert_eq!(cfg.custom_patterns[0].pattern, r"\b\d{5}\b");

            let dict = PyDict::new(py);
            let list = PyList::empty(py);
            list.append("^test@").unwrap();
            list.append("example\\.com").unwrap();
            dict.set_item("whitelist_patterns", list).unwrap();
            let cfg = PIIConfig::try_from_py_dict(&dict).unwrap();
            assert_eq!(cfg.whitelist_patterns.len(), 2);

            let dict = PyDict::new(py);
            let patterns_list = PyList::empty(py);
            let item = PyDict::new(py);
            item.set_item("description", "ZIP").unwrap();
            item.set_item("mask_strategy", "redact").unwrap();
            patterns_list.append(item).unwrap();
            dict.set_item("custom_patterns", patterns_list).unwrap();
            let err = PIIConfig::try_from_py_dict(&dict).expect_err("missing pattern should fail");
            assert!(matches!(
                err,
                ConfigError::MissingField {
                    field: "custom_patterns.pattern"
                }
            ));

            let dict = PyDict::new(py);
            dict.set_item("detect_ssn", "not_a_bool").unwrap();
            let err = PIIConfig::try_from_py_dict(&dict).expect_err("invalid type should fail");
            assert!(matches!(
                err,
                ConfigError::InvalidField {
                    field: "detect_ssn",
                    ..
                }
            ));

            let dict = PyDict::new(py);
            dict.set_item("default_mask_strategy", "bogus").unwrap();
            let err = PIIConfig::try_from_py_dict(&dict).expect_err("invalid strategy should fail");
            assert!(matches!(
                err,
                ConfigError::InvalidField {
                    field: "default_mask_strategy",
                    ..
                }
            ));

            let dict = PyDict::new(py);
            dict.set_item("custom_patterns", "not-a-list").unwrap();
            let err = PIIConfig::try_from_py_dict(&dict)
                .expect_err("non-list custom_patterns should fail");
            assert!(matches!(
                err,
                ConfigError::InvalidField {
                    field: "custom_patterns",
                    ..
                }
            ));

            let dict = PyDict::new(py);
            let patterns_list = PyList::empty(py);
            patterns_list.append("not-a-dict").unwrap();
            dict.set_item("custom_patterns", patterns_list).unwrap();
            let err = PIIConfig::try_from_py_dict(&dict)
                .expect_err("custom pattern entries must be dicts");
            assert!(matches!(
                err,
                ConfigError::InvalidField {
                    field: "custom_patterns",
                    ..
                }
            ));

            // --- py_list_to_detections_typed missing key -> ValueError
            let list = PyList::empty(py);
            let d = PyDict::new(py);
            d.set_item("value", "123-45-6789").unwrap();
            d.set_item("start", 0usize).unwrap();
            d.set_item("end", 11usize).unwrap();
            list.append(d).unwrap();
            let err = detector
                .py_list_to_detections_typed(&list.into_any())
                .expect_err("missing mask_strategy should fail")
                .to_py_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));

            let list = PyList::empty(py);
            let d = PyDict::new(py);
            d.set_item("value", "123-45-6789").unwrap();
            d.set_item("start", 0usize).unwrap();
            d.set_item("end", 11usize).unwrap();
            d.set_item("mask_strategy", "bogus").unwrap();
            list.append(d).unwrap();
            let err = detector
                .py_list_to_detections_typed(&list.into_any())
                .expect_err("invalid mask strategy should fail")
                .to_py_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));

            let list = PyList::empty(py);
            let d = PyDict::new(py);
            d.set_item("value", "123-45-6789").unwrap();
            d.set_item("start", 0usize).unwrap();
            d.set_item("end", 11usize).unwrap();
            d.set_item("mask_strategy", "partial").unwrap();
            d.set_item("description", 123).unwrap();
            list.append(d).unwrap();
            let err = detector
                .py_list_to_detections_typed(&list.into_any())
                .expect_err("invalid description type should fail")
                .to_py_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyValueError>(py));

            // --- try_new with invalid config returns Err
            let bad_dict = PyDict::new(py);
            let patterns_list = PyList::empty(py);
            let item = PyDict::new(py);
            item.set_item("description", "ZIP").unwrap();
            item.set_item("mask_strategy", "redact").unwrap();
            patterns_list.append(item).unwrap();
            bad_dict.set_item("custom_patterns", patterns_list).unwrap();
            let result = PIIDetectorRust::try_new(bad_dict.as_any());
            assert!(matches!(result, Err(PIIFilterError::Config(_))));

            // --- mask round-trip: detect -> mask -> assert PII was masked
            let text = "My SSN is 123-45-6789";
            let py_detections = detector.detect(py, text).unwrap();
            let masked = detector.mask(text, py_detections.bind(py)).unwrap();
            assert!(!masked.contains("123-45-6789"));
            assert!(masked.contains("***") || masked.contains("[REDACTED]"));

            // --- detect omits optional details when configured
            let config = PIIConfig {
                include_detection_details: false,
                detect_ssn: true,
                ..Default::default()
            };
            let patterns = compile_patterns(&config).unwrap();
            let detector_no_details = PIIDetectorRust { patterns, config };
            let py_detections = detector_no_details.detect(py, text).unwrap();
            let det_dict = py_detections.bind(py).cast::<PyDict>().unwrap();
            let ssn_items = det_dict.get_item("ssn").unwrap().unwrap();
            let det_list = ssn_items.cast::<PyList>().unwrap();
            let first_item = det_list.get_item(0).unwrap();
            let item = first_item.cast::<PyDict>().unwrap();
            assert!(item.get_item("description").unwrap().is_none());

            // --- block_on_detection prevents mutation paths
            let config = PIIConfig {
                block_on_detection: true,
                detect_ssn: true,
                ..Default::default()
            };
            let patterns = compile_patterns(&config).unwrap();
            let blocking_detector = PIIDetectorRust { patterns, config };
            let py_detections = blocking_detector.detect(py, text).unwrap();
            let err = blocking_detector
                .mask(text, py_detections.bind(py))
                .expect_err("block_on_detection should stop masking");
            assert!(err.is_instance_of::<pyo3::exceptions::PyRuntimeError>(py));

            // --- process_nested: string with PII
            let data = pyo3::types::PyString::new(py, "My SSN is 123-45-6789");
            let (modified, _new_data, _det) =
                detector.try_process_nested(py, data.as_any(), "").unwrap();
            assert!(modified);

            let data = pyo3::types::PyString::new(py, "My SSN is 123-45-6789");
            let err = blocking_detector
                .try_process_nested(py, data.as_any(), "")
                .expect_err("block_on_detection should stop nested masking")
                .to_py_err();
            assert!(err.is_instance_of::<pyo3::exceptions::PyRuntimeError>(py));

            // --- process_nested: dict with value that has PII
            let dict = PyDict::new(py);
            dict.set_item("secret", "SSN: 123-45-6789").unwrap();
            let (modified, _new_data, _det) =
                detector.try_process_nested(py, dict.as_any(), "").unwrap();
            assert!(modified);

            // --- process_nested: dict with non-string key should still be processed
            let dict = PyDict::new(py);
            dict.set_item(1, "SSN: 123-45-6789").unwrap();
            let (modified, _new_data, _det) =
                detector.try_process_nested(py, dict.as_any(), "").unwrap();
            assert!(modified);

            // --- process_nested: list with element that has PII
            let list = PyList::empty(py);
            list.append("SSN: 123-45-6789").unwrap();
            let (modified, _new_data, _det) =
                detector.try_process_nested(py, list.as_any(), "").unwrap();
            assert!(modified);

            // --- process_nested: non-string/dict/list leaves unchanged
            let data = pyo3::types::PyInt::new(py, 42);
            let (modified, _new_data, det) =
                detector.try_process_nested(py, data.as_any(), "").unwrap();
            assert!(!modified);
            let det_dict = det.bind(py).cast::<PyDict>().unwrap();
            assert_eq!(det_dict.len(), 0);
        });
    }

    #[test]
    fn test_detection_log_fields_only_include_safe_metadata() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_email: true,
            ..Default::default()
        };
        let patterns = compile_patterns(&config).unwrap();
        let detector = PIIDetectorRust { patterns, config };
        let detections = detector.detect_internal("Email john@example.com SSN 123-45-6789");
        let fields = detection_log_fields(Some("secret.token"), &detections);
        let serialized = format!("{fields:?}");

        assert_eq!(
            fields,
            DetectionLogFields {
                path_kind: "nested",
                path_depth: 2,
                pii_types: "email,ssn".to_string(),
                detection_count: 2,
            }
        );
        assert!(!serialized.contains("john@example.com"));
        assert!(!serialized.contains("123-45-6789"));
        assert!(!serialized.contains("secret"));
        assert!(!serialized.contains("token"));
    }
}
