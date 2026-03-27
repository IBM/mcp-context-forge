// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Configuration types for PII Filter

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict};
use serde::{Deserialize, Serialize};

const MAX_TEXT_BYTES_LIMIT: usize = 100 * 1024 * 1024;
const MAX_NESTED_DEPTH_LIMIT: usize = 1000;
const MAX_COLLECTION_ITEMS_LIMIT: usize = 1_000_000;
const DEFAULT_MAX_TEXT_BYTES: usize = 10 * 1024 * 1024;
const DEFAULT_MAX_NESTED_DEPTH: usize = 32;
const DEFAULT_MAX_COLLECTION_ITEMS: usize = 4096;

/// PII types that can be detected
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PIIType {
    Ssn,
    Bsn,
    CreditCard,
    Email,
    Phone,
    IpAddress,
    DateOfBirth,
    Passport,
    DriverLicense,
    BankAccount,
    MedicalRecord,
    AwsKey,
    ApiKey,
    Custom,
}

impl PIIType {
    /// Convert PIIType to string for Python
    pub fn as_str(&self) -> &'static str {
        match self {
            PIIType::Ssn => "ssn",
            PIIType::Bsn => "bsn",
            PIIType::CreditCard => "credit_card",
            PIIType::Email => "email",
            PIIType::Phone => "phone",
            PIIType::IpAddress => "ip_address",
            PIIType::DateOfBirth => "date_of_birth",
            PIIType::Passport => "passport",
            PIIType::DriverLicense => "driver_license",
            PIIType::BankAccount => "bank_account",
            PIIType::MedicalRecord => "medical_record",
            PIIType::AwsKey => "aws_key",
            PIIType::ApiKey => "api_key",
            PIIType::Custom => "custom",
        }
    }
}

/// Masking strategies for detected PII
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum MaskingStrategy {
    #[default]
    Redact, // Replace with [REDACTED]
    Partial,  // Show first/last chars (e.g., ***-**-1234)
    Hash,     // Replace with hash (e.g., [HASH:abc123])
    Tokenize, // Replace with token (e.g., [TOKEN:xyz789])
    Remove,   // Remove entirely
}

/// Custom pattern definition from Python
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CustomPattern {
    pub pattern: String,
    pub description: String,
    pub mask_strategy: MaskingStrategy,
    #[serde(default = "default_enabled")]
    pub enabled: bool,
}

fn default_enabled() -> bool {
    true
}

/// Configuration for PII Filter
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PIIConfig {
    // Detection flags
    pub detect_ssn: bool,
    pub detect_bsn: bool,
    pub detect_credit_card: bool,
    pub detect_email: bool,
    pub detect_phone: bool,
    pub detect_ip_address: bool,
    pub detect_date_of_birth: bool,
    pub detect_passport: bool,
    pub detect_driver_license: bool,
    pub detect_bank_account: bool,
    pub detect_medical_record: bool,
    pub detect_aws_keys: bool,
    pub detect_api_keys: bool,

    // Masking configuration
    pub default_mask_strategy: MaskingStrategy,
    pub redaction_text: String,

    // Behavior configuration
    pub block_on_detection: bool,
    pub log_detections: bool,
    pub include_detection_details: bool,

    // Resource limits
    pub max_text_bytes: usize,
    pub max_nested_depth: usize,
    pub max_collection_items: usize,

    // Custom patterns
    #[serde(default)]
    pub custom_patterns: Vec<CustomPattern>,

    // Whitelist patterns (regex strings)
    pub whitelist_patterns: Vec<String>,
}

impl Default for PIIConfig {
    fn default() -> Self {
        Self {
            // Enable all detections by default
            detect_ssn: true,
            detect_bsn: true,
            detect_credit_card: true,
            detect_email: true,
            detect_phone: true,
            detect_ip_address: true,
            detect_date_of_birth: true,
            detect_passport: true,
            detect_driver_license: true,
            detect_bank_account: true,
            detect_medical_record: true,
            detect_aws_keys: true,
            detect_api_keys: true,

            // Default masking
            default_mask_strategy: MaskingStrategy::Redact,
            redaction_text: "[REDACTED]".to_string(),

            // Default behavior
            block_on_detection: false,
            log_detections: true,
            include_detection_details: true,

            // Default resource limits
            max_text_bytes: DEFAULT_MAX_TEXT_BYTES,
            max_nested_depth: DEFAULT_MAX_NESTED_DEPTH,
            max_collection_items: DEFAULT_MAX_COLLECTION_ITEMS,

            // Custom patterns
            custom_patterns: Vec::new(),

            whitelist_patterns: Vec::new(),
        }
    }
}

impl PIIConfig {
    /// Extract configuration from Python object (dict or Pydantic model)
    pub fn from_py_object(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Try to convert to dict first (handles both dict and Pydantic models)
        let dict = if obj.is_instance_of::<PyDict>() {
            obj.cast::<PyDict>()?.clone()
        } else {
            // For Pydantic models, call model_dump() to get a dict
            let model_dump = obj.getattr("model_dump")?;
            let dict_obj = model_dump.call0()?;
            dict_obj.cast::<PyDict>()?.clone()
        };

        Self::from_py_dict(&dict)
    }

    /// Extract configuration from Python dict
    pub fn from_py_dict(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let mut config = Self::default();

        // Helper macro to extract boolean values
        macro_rules! extract_bool {
            ($field:ident) => {
                if let Some(value) = dict.get_item(stringify!($field))? {
                    config.$field = value.extract()?;
                }
            };
        }

        // Extract all boolean flags
        extract_bool!(detect_ssn);
        extract_bool!(detect_bsn);
        extract_bool!(detect_credit_card);
        extract_bool!(detect_email);
        extract_bool!(detect_phone);
        extract_bool!(detect_ip_address);
        extract_bool!(detect_date_of_birth);
        extract_bool!(detect_passport);
        extract_bool!(detect_driver_license);
        extract_bool!(detect_bank_account);
        extract_bool!(detect_medical_record);
        extract_bool!(detect_aws_keys);
        extract_bool!(detect_api_keys);
        extract_bool!(block_on_detection);
        extract_bool!(log_detections);
        extract_bool!(include_detection_details);

        if let Some(value) = dict.get_item("max_text_bytes")? {
            config.max_text_bytes = value.extract()?;
        }
        if let Some(value) = dict.get_item("max_nested_depth")? {
            config.max_nested_depth = value.extract()?;
        }
        if let Some(value) = dict.get_item("max_collection_items")? {
            config.max_collection_items = value.extract()?;
        }

        if config.max_text_bytes == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_text_bytes must be greater than 0",
            ));
        }
        if config.max_text_bytes > MAX_TEXT_BYTES_LIMIT {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "max_text_bytes must be less than or equal to {}",
                MAX_TEXT_BYTES_LIMIT
            )));
        }
        if config.max_nested_depth == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_nested_depth must be greater than 0",
            ));
        }
        if config.max_nested_depth > MAX_NESTED_DEPTH_LIMIT {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "max_nested_depth must be less than or equal to {}",
                MAX_NESTED_DEPTH_LIMIT
            )));
        }
        if config.max_collection_items == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_collection_items must be greater than 0",
            ));
        }
        if config.max_collection_items > MAX_COLLECTION_ITEMS_LIMIT {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "max_collection_items must be less than or equal to {}",
                MAX_COLLECTION_ITEMS_LIMIT
            )));
        }

        // Extract string values
        if let Some(value) = dict.get_item("redaction_text")? {
            config.redaction_text = value.extract()?;
        }

        // Extract mask strategy
        if let Some(value) = dict.get_item("default_mask_strategy")? {
            let strategy_str: String = value.extract()?;
            config.default_mask_strategy = match strategy_str.as_str() {
                "redact" => MaskingStrategy::Redact,
                "partial" => MaskingStrategy::Partial,
                "hash" => MaskingStrategy::Hash,
                "tokenize" => MaskingStrategy::Tokenize,
                "remove" => MaskingStrategy::Remove,
                _ => MaskingStrategy::Redact,
            };
        }

        // Extract custom patterns
        if let Some(value) = dict.get_item("custom_patterns")?
            && let Ok(py_list) = value.cast::<pyo3::types::PyList>()
        {
            for item in py_list.iter() {
                if let Ok(py_dict) = item.cast::<PyDict>() {
                    let pattern: String = py_dict
                        .get_item("pattern")?
                        .ok_or_else(|| {
                            pyo3::exceptions::PyValueError::new_err("Missing 'pattern' field")
                        })?
                        .extract()?;
                    let description: String = py_dict
                        .get_item("description")?
                        .ok_or_else(|| {
                            pyo3::exceptions::PyValueError::new_err("Missing 'description' field")
                        })?
                        .extract()?;
                    let mask_strategy_str: String = match py_dict.get_item("mask_strategy")? {
                        Some(val) => val.extract()?,
                        None => "redact".to_string(),
                    };
                    let enabled: bool = match py_dict.get_item("enabled")? {
                        Some(val) => val.extract()?,
                        None => true,
                    };

                    let mask_strategy = match mask_strategy_str.as_str() {
                        "redact" => MaskingStrategy::Redact,
                        "partial" => MaskingStrategy::Partial,
                        "hash" => MaskingStrategy::Hash,
                        "tokenize" => MaskingStrategy::Tokenize,
                        "remove" => MaskingStrategy::Remove,
                        _ => MaskingStrategy::Redact,
                    };

                    config.custom_patterns.push(CustomPattern {
                        pattern,
                        description,
                        mask_strategy,
                        enabled,
                    });
                }
            }
        }

        // Extract whitelist patterns
        if let Some(value) = dict.get_item("whitelist_patterns")? {
            config.whitelist_patterns = value.extract()?;
        }

        Ok(config)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDict;

    #[test]
    fn test_pii_type_as_str() {
        assert_eq!(PIIType::Ssn.as_str(), "ssn");
        assert_eq!(PIIType::CreditCard.as_str(), "credit_card");
        assert_eq!(PIIType::Email.as_str(), "email");
    }

    #[test]
    fn test_default_config() {
        let config = PIIConfig::default();
        assert!(config.detect_ssn);
        assert!(config.detect_email);
        assert_eq!(config.redaction_text, "[REDACTED]");
        assert_eq!(config.default_mask_strategy, MaskingStrategy::Redact);
        assert_eq!(config.max_text_bytes, DEFAULT_MAX_TEXT_BYTES);
        assert_eq!(config.max_nested_depth, DEFAULT_MAX_NESTED_DEPTH);
        assert_eq!(config.max_collection_items, DEFAULT_MAX_COLLECTION_ITEMS);
    }

    #[test]
    fn test_from_py_dict_rejects_excessive_resource_limits() {
        Python::initialize();
        Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("max_text_bytes", 100 * 1024 * 1024 + 1)
                .unwrap();

            let err = PIIConfig::from_py_dict(&dict).unwrap_err();
            assert!(err.to_string().contains("max_text_bytes"));
        });
    }

    #[test]
    fn test_from_py_dict_rejects_excessive_nested_depth() {
        Python::initialize();
        Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("max_nested_depth", MAX_NESTED_DEPTH_LIMIT + 1)
                .unwrap();

            let err = PIIConfig::from_py_dict(&dict).unwrap_err();
            assert!(err.to_string().contains("max_nested_depth"));
        });
    }

    #[test]
    fn test_from_py_dict_rejects_excessive_collection_items() {
        Python::initialize();
        Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("max_collection_items", MAX_COLLECTION_ITEMS_LIMIT + 1)
                .unwrap();

            let err = PIIConfig::from_py_dict(&dict).unwrap_err();
            assert!(err.to_string().contains("max_collection_items"));
        });
    }
}
