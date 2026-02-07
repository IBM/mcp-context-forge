// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Configuration types for PII Filter

use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};

/// PII types that can be detected
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PIIType {
    Ssn,
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

            // Custom patterns
            custom_patterns: Vec::new(),

            whitelist_patterns: Vec::new(),
        }
    }
}

impl PIIConfig {
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
    }
}
