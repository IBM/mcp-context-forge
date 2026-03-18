// SPDX-License-Identifier: Apache-2.0
//! Configuration types and Python dict parsing for the PII filter.

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyDict};
use pythonize::depythonize;
use serde::{Deserialize, Serialize};

use super::error::ConfigError;

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
    FullName,
    StreetAddress,
    UsAbaRoutingNumber,
    UsZipCode,
    UsEin,
    UsItin,
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
            PIIType::FullName => "full_name",
            PIIType::StreetAddress => "street_address",
            PIIType::UsAbaRoutingNumber => "us_aba_routing_number",
            PIIType::UsZipCode => "us_zip_code",
            PIIType::UsEin => "us_ein",
            PIIType::UsItin => "us_itin",
            PIIType::Custom => "custom",
        }
    }
}

/// Masking strategies for detected PII
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum MaskingStrategy {
    #[default]
    Auto, // Use per-pattern defaults that fit the PII type
    Redact,   // Replace with [REDACTED]
    Partial,  // Show first/last chars (e.g., ***-**-1234)
    Hash,     // Replace with hash (e.g., [HASH:abc123])
    Tokenize, // Replace with token (e.g., [TOKEN:xyz789])
    Remove,   // Remove entirely
}

impl MaskingStrategy {
    /// String for Python/API exposure (snake_case).
    pub fn as_str(self) -> &'static str {
        match self {
            MaskingStrategy::Auto => "auto",
            MaskingStrategy::Redact => "redact",
            MaskingStrategy::Partial => "partial",
            MaskingStrategy::Hash => "hash",
            MaskingStrategy::Tokenize => "tokenize",
            MaskingStrategy::Remove => "remove",
        }
    }

    /// Parse a masking strategy from user-provided configuration.
    pub fn parse(value: &str, field: &'static str) -> Result<Self, ConfigError> {
        match value {
            "default" | "auto" => Ok(MaskingStrategy::Auto),
            "redact" => Ok(MaskingStrategy::Redact),
            "partial" => Ok(MaskingStrategy::Partial),
            "hash" => Ok(MaskingStrategy::Hash),
            "tokenize" => Ok(MaskingStrategy::Tokenize),
            "remove" => Ok(MaskingStrategy::Remove),
            _ => Err(ConfigError::InvalidField {
                field,
                details: format!(
                    "unsupported masking strategy '{value}' (expected one of: default, redact, partial, hash, tokenize, remove)"
                ),
            }),
        }
    }
}

/// Custom pattern definition from Python
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CustomPattern {
    /// Regex pattern string for detection
    pub pattern: String,
    /// Human-readable description of the pattern
    pub description: String,
    /// How to mask matches (redact, partial, hash, tokenize, remove)
    pub mask_strategy: MaskingStrategy,
    #[serde(default = "default_enabled")]
    /// Whether this pattern is enabled
    pub enabled: bool,
}

fn default_enabled() -> bool {
    true
}

fn default_redact_mask_strategy() -> String {
    "redact".to_string()
}

fn validate_redaction_text(redaction_text: String) -> Result<String, ConfigError> {
    if redaction_text.is_empty() {
        return Err(ConfigError::InvalidField {
            field: "redaction_text",
            details: "redaction_text cannot be empty".to_string(),
        });
    }
    Ok(redaction_text)
}

/// Configuration for PII Filter
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PIIConfig {
    /// Detect Social Security Numbers
    pub detect_ssn: bool,
    /// Detect Dutch BSN (Burgerservicenummer)
    pub detect_bsn: bool,
    /// Detect credit card numbers (Luhn-validated)
    pub detect_credit_card: bool,
    /// Detect email addresses
    pub detect_email: bool,
    /// Detect libphonenumber-validated U.S. domestic formats and international numbers with country code
    pub detect_phone: bool,
    /// Detect IPv4 and standard fully expanded or compressed IPv6 addresses
    pub detect_ip_address: bool,
    /// Detect dates of birth with DOB or birth-date style context
    pub detect_date_of_birth: bool,
    /// Detect U.S. (9 digits) and EU-style (2 letters + 7 digits) passport numbers with passport label or U.S. / EU region marker
    pub detect_passport: bool,
    /// Detect driver license numbers for CA, TX, FL, and NY with driver-license label or state marker
    pub detect_driver_license: bool,
    /// Detect contextual 8-17 digit bank account numbers and checksum-validated IBAN
    pub detect_bank_account: bool,
    /// Detect contextual MRN / Medical Record identifiers
    pub detect_medical_record: bool,
    /// Detect labeled full names
    pub detect_full_name: bool,
    /// Detect labeled street addresses with common English street suffixes
    pub detect_street_address: bool,
    /// Detect checksum-valid U.S. ABA routing transit numbers
    pub detect_us_aba_routing_number: bool,
    /// Detect labeled US ZIP codes
    pub detect_us_zip_code: bool,
    /// Detect labeled U.S. employer identification numbers
    pub detect_us_ein: bool,
    /// Detect labeled U.S. individual taxpayer identification numbers
    pub detect_us_itin: bool,

    /// Default masking strategy when not per-pattern
    pub default_mask_strategy: MaskingStrategy,
    /// Text used for redaction (e.g. `[REDACTED]`)
    pub redaction_text: String,

    /// Whether to block on detection
    pub block_on_detection: bool,
    /// Whether to log detections
    pub log_detections: bool,
    /// Whether to include detection details in output
    pub include_detection_details: bool,

    /// User-defined regex patterns
    #[serde(default)]
    pub custom_patterns: Vec<CustomPattern>,

    /// Regex patterns that exclude matches from detection (whitelist)
    #[serde(default)]
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
            detect_full_name: true,
            detect_street_address: true,
            detect_us_aba_routing_number: true,
            detect_us_zip_code: true,
            detect_us_ein: true,
            detect_us_itin: true,

            // Default masking
            default_mask_strategy: MaskingStrategy::Auto,
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

/// Helper: get an optional typed value from a Python dict.
fn get_optional<T>(dict: &Bound<'_, PyDict>, key: &'static str) -> Result<Option<T>, ConfigError>
where
    for<'py> T: FromPyObject<'py, 'py, Error = PyErr>,
{
    let value = dict
        .get_item(key)
        .map_err(|e: PyErr| ConfigError::InvalidField {
            field: key,
            details: e.to_string(),
        })?;
    match value {
        None => Ok(None),
        Some(v) => v
            .extract()
            .map(Some)
            .map_err(|e: PyErr| ConfigError::InvalidField {
                field: key,
                details: e.to_string(),
            }),
    }
}

fn get_optional_bool(
    dict: &Bound<'_, PyDict>,
    key: &'static str,
) -> Result<Option<bool>, ConfigError> {
    let value = dict
        .get_item(key)
        .map_err(|e: PyErr| ConfigError::InvalidField {
            field: key,
            details: e.to_string(),
        })?;
    match value {
        None => Ok(None),
        Some(v) => {
            if !v.is_instance_of::<PyBool>() {
                return Err(ConfigError::InvalidField {
                    field: key,
                    details: "expected bool".to_string(),
                });
            }
            v.extract()
                .map(Some)
                .map_err(|e: PyErr| ConfigError::InvalidField {
                    field: key,
                    details: e.to_string(),
                })
        }
    }
}

#[derive(Debug, Deserialize)]
struct PyCustomPatternInput {
    pattern: Option<String>,
    description: Option<String>,
    #[serde(default = "default_redact_mask_strategy")]
    mask_strategy: String,
    #[serde(default = "default_enabled")]
    enabled: bool,
}

fn custom_pattern_from_input(input: PyCustomPatternInput) -> Result<CustomPattern, ConfigError> {
    let pattern = input.pattern.ok_or(ConfigError::MissingField {
        field: "custom_patterns.pattern",
    })?;
    if pattern.is_empty() {
        return Err(ConfigError::InvalidField {
            field: "custom_patterns.pattern",
            details: "pattern cannot be empty".to_string(),
        });
    }
    let description = input.description.ok_or(ConfigError::MissingField {
        field: "custom_patterns.description",
    })?;
    if description.trim().is_empty() {
        return Err(ConfigError::InvalidField {
            field: "custom_patterns.description",
            details: "description cannot be empty".to_string(),
        });
    }
    let mask_strategy = MaskingStrategy::parse(
        input.mask_strategy.as_str(),
        "custom_patterns.mask_strategy",
    )?;
    Ok(CustomPattern {
        pattern,
        description,
        mask_strategy,
        enabled: input.enabled,
    })
}

impl PIIConfig {
    /// Extract configuration from Python object (dict or Pydantic model)
    pub fn from_py_object(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        Self::try_from_py_object(obj)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    /// Typed config parsing from Python object (converted to PyErr at boundary)
    pub fn try_from_py_object(obj: &Bound<'_, PyAny>) -> Result<Self, ConfigError> {
        // Try to convert to dict first (handles both dict and Pydantic models)
        let dict = if obj.is_instance_of::<PyDict>() {
            obj.cast::<PyDict>()
                .map_err(|e| ConfigError::InvalidField {
                    field: "config",
                    details: e.to_string(),
                })?
                .clone()
        } else {
            // For Pydantic models, call model_dump() to get a dict
            let model_dump = obj
                .getattr("model_dump")
                .map_err(|e| ConfigError::InvalidField {
                    field: "config",
                    details: e.to_string(),
                })?;
            let dict_obj = model_dump.call0().map_err(|e| ConfigError::InvalidField {
                field: "config",
                details: e.to_string(),
            })?;
            dict_obj
                .cast::<PyDict>()
                .map_err(|e| ConfigError::InvalidField {
                    field: "config",
                    details: e.to_string(),
                })?
                .clone()
        };

        Self::try_from_py_dict(&dict)
    }

    /// Extract configuration from Python dict
    pub fn from_py_dict(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        Self::try_from_py_dict(dict)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    /// Typed config parsing (converted to PyErr at boundary)
    pub fn try_from_py_dict(dict: &Bound<'_, PyDict>) -> Result<Self, ConfigError> {
        let mut config = Self::default();

        // Extract boolean flags via helper
        if let Some(b) = get_optional_bool(dict, "detect_ssn")? {
            config.detect_ssn = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_bsn")? {
            config.detect_bsn = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_credit_card")? {
            config.detect_credit_card = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_email")? {
            config.detect_email = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_phone")? {
            config.detect_phone = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_ip_address")? {
            config.detect_ip_address = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_date_of_birth")? {
            config.detect_date_of_birth = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_passport")? {
            config.detect_passport = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_driver_license")? {
            config.detect_driver_license = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_bank_account")? {
            config.detect_bank_account = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_medical_record")? {
            config.detect_medical_record = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_full_name")? {
            config.detect_full_name = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_street_address")? {
            config.detect_street_address = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_us_aba_routing_number")? {
            config.detect_us_aba_routing_number = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_us_zip_code")? {
            config.detect_us_zip_code = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_us_ein")? {
            config.detect_us_ein = b;
        }
        if let Some(b) = get_optional_bool(dict, "detect_us_itin")? {
            config.detect_us_itin = b;
        }
        if let Some(b) = get_optional_bool(dict, "block_on_detection")? {
            config.block_on_detection = b;
        }
        if let Some(b) = get_optional_bool(dict, "log_detections")? {
            config.log_detections = b;
        }
        if let Some(b) = get_optional_bool(dict, "include_detection_details")? {
            config.include_detection_details = b;
        }

        if let Some(s) = get_optional::<String>(dict, "redaction_text")? {
            config.redaction_text = validate_redaction_text(s)?;
        }

        if let Some(s) = get_optional::<String>(dict, "default_mask_strategy")? {
            config.default_mask_strategy =
                MaskingStrategy::parse(s.as_str(), "default_mask_strategy")?;
        }

        if let Some(value) =
            dict.get_item("custom_patterns")
                .map_err(|e: PyErr| ConfigError::InvalidField {
                    field: "custom_patterns",
                    details: e.to_string(),
                })?
        {
            let patterns: Vec<PyCustomPatternInput> =
                depythonize(&value).map_err(|e| ConfigError::InvalidField {
                    field: "custom_patterns",
                    details: e.to_string(),
                })?;
            for item in patterns {
                config
                    .custom_patterns
                    .push(custom_pattern_from_input(item)?);
            }
        }

        if let Some(value) =
            dict.get_item("whitelist_patterns")
                .map_err(|e: PyErr| ConfigError::InvalidField {
                    field: "whitelist_patterns",
                    details: e.to_string(),
                })?
        {
            config.whitelist_patterns =
                value
                    .extract()
                    .map_err(|e: PyErr| ConfigError::InvalidField {
                        field: "whitelist_patterns",
                        details: e.to_string(),
                    })?;
        }

        Ok(config)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pii_type_as_str_all_variants() {
        assert_eq!(PIIType::Ssn.as_str(), "ssn");
        assert_eq!(PIIType::Bsn.as_str(), "bsn");
        assert_eq!(PIIType::CreditCard.as_str(), "credit_card");
        assert_eq!(PIIType::Email.as_str(), "email");
        assert_eq!(PIIType::Phone.as_str(), "phone");
        assert_eq!(PIIType::IpAddress.as_str(), "ip_address");
        assert_eq!(PIIType::DateOfBirth.as_str(), "date_of_birth");
        assert_eq!(PIIType::Passport.as_str(), "passport");
        assert_eq!(PIIType::DriverLicense.as_str(), "driver_license");
        assert_eq!(PIIType::BankAccount.as_str(), "bank_account");
        assert_eq!(PIIType::MedicalRecord.as_str(), "medical_record");
        assert_eq!(PIIType::FullName.as_str(), "full_name");
        assert_eq!(PIIType::StreetAddress.as_str(), "street_address");
        assert_eq!(
            PIIType::UsAbaRoutingNumber.as_str(),
            "us_aba_routing_number"
        );
        assert_eq!(PIIType::UsZipCode.as_str(), "us_zip_code");
        assert_eq!(PIIType::UsEin.as_str(), "us_ein");
        assert_eq!(PIIType::UsItin.as_str(), "us_itin");
        assert_eq!(PIIType::Custom.as_str(), "custom");
    }

    #[test]
    fn test_default_config() {
        let config = PIIConfig::default();
        assert!(config.detect_ssn);
        assert!(config.detect_email);
        assert!(config.detect_full_name);
        assert!(config.detect_driver_license);
        assert!(config.detect_us_aba_routing_number);
        assert_eq!(config.redaction_text, "[REDACTED]");
        assert_eq!(config.default_mask_strategy, MaskingStrategy::Auto);
    }

    #[test]
    fn test_masking_strategy_parse_rejects_unknown_value() {
        let err = MaskingStrategy::parse("surprise", "default_mask_strategy")
            .expect_err("unknown strategies should fail fast");
        assert!(matches!(
            err,
            ConfigError::InvalidField {
                field: "default_mask_strategy",
                ..
            }
        ));
    }

    #[test]
    fn test_masking_strategy_parse_accepts_default_aliases() {
        assert_eq!(
            MaskingStrategy::parse("default", "default_mask_strategy").unwrap(),
            MaskingStrategy::Auto
        );
        assert_eq!(
            MaskingStrategy::parse("auto", "default_mask_strategy").unwrap(),
            MaskingStrategy::Auto
        );
    }

    #[test]
    fn test_redaction_text_cannot_be_empty() {
        let err =
            validate_redaction_text(String::new()).expect_err("empty redaction text should fail");
        assert!(matches!(
            err,
            ConfigError::InvalidField {
                field: "redaction_text",
                ..
            }
        ));
    }

    // try_from_py_dict tests run in detector::tests::test_python_api to avoid
    // multiple Python::attach calls in the same process (which can block).
}
