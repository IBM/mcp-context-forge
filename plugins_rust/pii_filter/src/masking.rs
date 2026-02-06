// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Masking strategies for detected PII

use sha2::{Digest, Sha256};
use std::borrow::Cow;
use std::collections::HashMap;
use uuid::Uuid;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::detector::Detection;

/// Apply masking to detected PII in text
///
/// # Arguments
/// * `text` - Original text containing PII
/// * `detections` - Map of PIIType to detected instances
/// * `config` - Configuration with masking preferences
///
/// # Returns
/// Masked text with PII replaced according to strategies
pub fn mask_pii<'a>(
    text: &'a str,
    detections: &HashMap<PIIType, Vec<Detection>>,
    config: &PIIConfig,
) -> Cow<'a, str> {
    if detections.is_empty() {
        // Zero-copy optimization when no masking needed
        return Cow::Borrowed(text);
    }

    // Collect all detections with their positions
    let mut all_detections: Vec<(&Detection, PIIType)> = Vec::new();
    for (pii_type, items) in detections {
        for detection in items {
            all_detections.push((detection, *pii_type));
        }
    }

    // Sort by start position (reverse order for stable replacement)
    all_detections.sort_by(|a, b| b.0.start.cmp(&a.0.start));

    // Apply masking from end to start
    let mut result = text.to_string();
    for (detection, pii_type) in all_detections {
        let masked_value =
            apply_mask_strategy(&detection.value, pii_type, detection.mask_strategy, config);

        result.replace_range(detection.start..detection.end, &masked_value);
    }

    Cow::Owned(result)
}

/// Apply specific masking strategy to a value
fn apply_mask_strategy(
    value: &str,
    pii_type: PIIType,
    strategy: MaskingStrategy,
    config: &PIIConfig,
) -> String {
    match strategy {
        MaskingStrategy::Redact => config.redaction_text.clone(),
        MaskingStrategy::Partial => partial_mask(value, pii_type),
        MaskingStrategy::Hash => hash_mask(value),
        MaskingStrategy::Tokenize => tokenize_mask(),
        MaskingStrategy::Remove => String::new(),
    }
}

/// Partial masking - show first/last characters based on PII type
fn partial_mask(value: &str, pii_type: PIIType) -> String {
    match pii_type {
        PIIType::Ssn => {
            // Show last 4 digits: ***-**-1234
            if value.len() >= 4 {
                format!("***-**-{}", &value[value.len() - 4..])
            } else {
                "***-**-****".to_string()
            }
        }

        PIIType::CreditCard => {
            // Show last 4 digits: ****-****-****-1234
            let digits_only: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
            if digits_only.len() >= 4 {
                format!("****-****-****-{}", &digits_only[digits_only.len() - 4..])
            } else {
                "****-****-****-****".to_string()
            }
        }

        PIIType::Email => {
            // Show first + last char before @: j***e@example.com
            if let Some(at_pos) = value.find('@') {
                let local = &value[..at_pos];
                let domain = &value[at_pos..];

                if local.len() > 2 {
                    format!("{}***{}{}", &local[..1], &local[local.len() - 1..], domain)
                } else {
                    format!("***{}", domain)
                }
            } else {
                "[REDACTED]".to_string()
            }
        }

        PIIType::Phone => {
            // Show last 4 digits: ***-***-1234
            let digits_only: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
            if digits_only.len() >= 4 {
                format!("***-***-{}", &digits_only[digits_only.len() - 4..])
            } else {
                "***-***-****".to_string()
            }
        }

        PIIType::BankAccount => {
            // Show last 4 for IBAN-like, redact others
            if value.len() >= 4 && value.chars().any(|c| c.is_ascii_alphabetic()) {
                // IBAN format: XX**************1234
                format!(
                    "{}{}",
                    &value[..2],
                    "*".repeat(value.len() - 6) + &value[value.len() - 4..]
                )
            } else {
                "[REDACTED]".to_string()
            }
        }

        _ => {
            // Generic partial masking: first + last char
            if value.len() > 2 {
                format!(
                    "{}{}{}",
                    &value[..1],
                    "*".repeat(value.len() - 2),
                    &value[value.len() - 1..]
                )
            } else if value.len() == 2 {
                format!("{}*", &value[..1])
            } else {
                "*".to_string()
            }
        }
    }
}

/// Hash masking using SHA256
fn hash_mask(value: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    let result = hasher.finalize();
    format!("[HASH:{}]", &format!("{:x}", result)[..8])
}

/// Tokenize using UUID v4
fn tokenize_mask() -> String {
    let token = Uuid::new_v4();
    format!("[TOKEN:{}]", &token.simple().to_string()[..8])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_partial_mask_ssn() {
        let result = partial_mask("123-45-6789", PIIType::Ssn);
        assert_eq!(result, "***-**-6789");
    }

    #[test]
    fn test_partial_mask_credit_card() {
        let result = partial_mask("4111-1111-1111-1111", PIIType::CreditCard);
        assert_eq!(result, "****-****-****-1111");
    }

    #[test]
    fn test_partial_mask_email() {
        let result = partial_mask("john.doe@example.com", PIIType::Email);
        assert!(result.contains("@example.com"));
        assert!(result.starts_with("j"));
    }

    #[test]
    fn test_hash_mask() {
        let result = hash_mask("sensitive");
        assert!(result.starts_with("[HASH:"));
        assert!(result.ends_with("]"));
        assert_eq!(result.len(), 15); // [HASH:xxxxxxxx]
    }

    #[test]
    fn test_tokenize_mask() {
        let result = tokenize_mask();
        assert!(result.starts_with("[TOKEN:"));
        assert!(result.ends_with("]"));
    }

    #[test]
    fn test_mask_pii_empty() {
        let config = PIIConfig::default();
        let detections = HashMap::new();
        let text = "No PII here";

        let result = mask_pii(text, &detections, &config);
        assert_eq!(result, text); // Zero-copy
    }
}
