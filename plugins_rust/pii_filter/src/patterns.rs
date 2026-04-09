// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Regex pattern compilation for PII detection
// Uses RegexSet for parallel matching (5-10x faster than sequential)

use once_cell::sync::Lazy;
use regex::{Regex, RegexSet};

use super::config::{MaskingStrategy, PIIConfig, PIIType};

/// Compiled pattern with metadata
#[derive(Debug, Clone)]
pub struct CompiledPattern {
    pub pii_type: PIIType,
    pub regex: Regex,
    pub mask_strategy: Option<MaskingStrategy>,
    #[allow(dead_code)]
    pub description: String,
}

/// All compiled patterns with RegexSet for parallel matching
pub struct CompiledPatterns {
    pub regex_set: RegexSet,
    pub patterns: Vec<CompiledPattern>,
    pub whitelist: Vec<Regex>,
}

/// Pattern definitions (pattern, description, explicit masking strategy)
type PatternDef = (&'static str, &'static str, MaskingStrategy);

const VALID_SSN_DASHED_PATTERN: &str = r"\b(?:00[1-9]|0[1-9][0-9]|[1-5][0-9]{2}|6(?:[0-5][0-9]|6[0-57-9]|[7-9][0-9])|[7-8][0-9]{2})-(?:0[1-9]|[1-9][0-9])-(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})\b";
const VALID_SSN_CONTEXTUAL_PATTERN: &str = r"\b(?:SSN|Social\s+Security(?:\s+Number)?)[:\s#-]*(?:00[1-9]|0[1-9][0-9]|[1-5][0-9]{2}|6(?:[0-5][0-9]|6[0-57-9]|[7-9][0-9])|[7-8][0-9]{2})(?:0[1-9]|[1-9][0-9])(?:000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})\b";

// SSN patterns
static SSN_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            VALID_SSN_DASHED_PATTERN,
            "US Social Security Number",
            MaskingStrategy::Partial,
        ),
        (
            VALID_SSN_CONTEXTUAL_PATTERN,
            "US Social Security Number with explicit context",
            MaskingStrategy::Partial,
        ),
    ]
});

// BSN patterns (Dutch Burgerservicenummer)
// Match 9-digit numbers only with explicit BSN-style context to avoid broad false positives.
static BSN_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\b(?:BSN|Citizen\s+ID|Citizen\s+Service\s+Number|Burgerservicenummer)[:\s#]*\d{9}\b",
            "Dutch BSN with explicit context",
            MaskingStrategy::Partial,
        ),
        (
            r"\b(?:My\s+)?BSN\s+(?:is\s+)?\d{9}\b",
            "BSN with 'is' context",
            MaskingStrategy::Partial,
        ),
    ]
});

// Credit card patterns
static CREDIT_CARD_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "Credit card number",
        MaskingStrategy::Partial,
    )]
});

// Email patterns
static EMAIL_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "Email address",
        MaskingStrategy::Partial,
    )]
});

// Phone patterns (US and international)
static PHONE_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            "US phone number",
            MaskingStrategy::Partial,
        ),
        (
            r"\+[1-9]\d{9,14}\b",
            "International phone number",
            MaskingStrategy::Partial,
        ),
    ]
});

// IP address patterns (IPv4 and IPv6)
static IP_ADDRESS_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
            "IPv4 address",
            MaskingStrategy::Redact,
        ),
        (
            r"\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b",
            "IPv6 address",
            MaskingStrategy::Redact,
        ),
    ]
});

// Date of birth patterns
static DOB_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\b(?:DOB|Date of Birth|Born|Birthday)[:\s]+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
            "Date of birth with label",
            MaskingStrategy::Redact,
        ),
        (
            r"\b(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])[-/](?:19|20)\d{2}\b",
            "Date in MM/DD/YYYY format",
            MaskingStrategy::Redact,
        ),
    ]
});

// Passport patterns
static PASSPORT_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b(?:Passport\s+Number|Passport\s+No|Passport)[#:\s-]+[A-Z0-9]{6,9}\b",
        "Passport number with explicit context",
        MaskingStrategy::Redact,
    )]
});

// Driver's license patterns
static DRIVER_LICENSE_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b(?:DL|License|Driver'?s? License)[#:\s]+[A-Z0-9]{5,20}\b",
        "Driver's license number",
        MaskingStrategy::Redact,
    )]
});

// Bank account patterns
static BANK_ACCOUNT_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\b(?:Account|Acct|Bank\s+Account|Account\s+Number|Routing\s+Account)[#:\s-]*\d{8,17}\b",
            "Bank account number with explicit context",
            MaskingStrategy::Redact,
        ),
        (
            r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:\d{3})?\b",
            "IBAN",
            MaskingStrategy::Partial,
        ),
    ]
});

// Medical record patterns
static MEDICAL_RECORD_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b(?:MRN|Medical Record)[#:\s]+[A-Z0-9]{6,12}\b",
        "Medical record number",
        MaskingStrategy::Redact,
    )]
});

/// Compile patterns based on configuration
pub fn compile_patterns(config: &PIIConfig) -> Result<CompiledPatterns, String> {
    let mut pattern_strings = Vec::new();
    let mut patterns = Vec::new();

    // Helper macro to add patterns with case-insensitive matching (match Python behavior)
    macro_rules! add_patterns {
        ($enabled:expr, $pii_type:expr, $pattern_list:expr) => {
            if $enabled {
                for (pattern, description, mask_strategy) in $pattern_list.iter() {
                    // Add case-insensitive flag to pattern string for RegexSet
                    pattern_strings.push(format!("(?i){}", pattern));
                    let regex = regex::RegexBuilder::new(pattern)
                        .case_insensitive(true)
                        .build()
                        .map_err(|e| format!("Failed to compile pattern '{}': {}", pattern, e))?;
                    patterns.push(CompiledPattern {
                        pii_type: $pii_type,
                        regex,
                        mask_strategy: Some(*mask_strategy),
                        description: description.to_string(),
                    });
                }
            }
        };
    }

    // Add patterns based on config
    add_patterns!(config.detect_bsn, PIIType::Bsn, &*BSN_PATTERNS);
    add_patterns!(config.detect_ssn, PIIType::Ssn, &*SSN_PATTERNS);
    add_patterns!(
        config.detect_credit_card,
        PIIType::CreditCard,
        &*CREDIT_CARD_PATTERNS
    );
    add_patterns!(config.detect_email, PIIType::Email, &*EMAIL_PATTERNS);
    add_patterns!(config.detect_phone, PIIType::Phone, &*PHONE_PATTERNS);
    add_patterns!(
        config.detect_ip_address,
        PIIType::IpAddress,
        &*IP_ADDRESS_PATTERNS
    );
    add_patterns!(
        config.detect_date_of_birth,
        PIIType::DateOfBirth,
        &*DOB_PATTERNS
    );
    add_patterns!(
        config.detect_passport,
        PIIType::Passport,
        &*PASSPORT_PATTERNS
    );
    add_patterns!(
        config.detect_driver_license,
        PIIType::DriverLicense,
        &*DRIVER_LICENSE_PATTERNS
    );
    add_patterns!(
        config.detect_bank_account,
        PIIType::BankAccount,
        &*BANK_ACCOUNT_PATTERNS
    );
    add_patterns!(
        config.detect_medical_record,
        PIIType::MedicalRecord,
        &*MEDICAL_RECORD_PATTERNS
    );

    // Add custom patterns
    for custom in &config.custom_patterns {
        if custom.enabled {
            validate_custom_pattern(&custom.pattern)?;

            // Add case-insensitive flag to pattern string for RegexSet
            pattern_strings.push(format!("(?i){}", custom.pattern));
            let regex = regex::RegexBuilder::new(&custom.pattern)
                .case_insensitive(true)
                .build()
                .map_err(|e| {
                    format!(
                        "Failed to compile custom pattern '{}': {}",
                        custom.pattern, e
                    )
                })?;
            patterns.push(CompiledPattern {
                pii_type: PIIType::Custom,
                regex,
                mask_strategy: Some(custom.mask_strategy),
                description: custom.description.clone(),
            });
        }
    }

    // Compile RegexSet for parallel matching
    // Handle empty pattern set gracefully (all detectors disabled)
    let regex_set = if pattern_strings.is_empty() {
        RegexSet::empty()
    } else {
        RegexSet::new(&pattern_strings).map_err(|e| format!("Failed to compile RegexSet: {}", e))?
    };

    // Compile whitelist patterns with error checking and case-insensitive (match Python behavior)
    let mut whitelist = Vec::new();
    for pattern in &config.whitelist_patterns {
        match regex::RegexBuilder::new(pattern)
            .case_insensitive(true)
            .build()
        {
            Ok(regex) => whitelist.push(regex),
            Err(e) => return Err(format!("Invalid whitelist pattern '{}': {}", pattern, e)),
        }
    }

    Ok(CompiledPatterns {
        regex_set,
        patterns,
        whitelist,
    })
}

/// Validate admin-authored custom patterns before compilation.
///
/// These patterns come from trusted plugin configuration rather than end-user input.
/// The Rust `regex` crate uses a linear-time engine without catastrophic backtracking,
/// so these limits are lightweight guardrails for readability, compile cost, and
/// obvious mistakes instead of a full regex sandbox.
fn validate_custom_pattern(pattern: &str) -> Result<(), String> {
    const MAX_CUSTOM_PATTERN_LEN: usize = 256;
    const MAX_ALTERNATIONS: usize = 16;
    const MAX_QUANTIFIERS: usize = 24;

    if pattern.trim().is_empty() {
        return Err("Custom pattern cannot be empty".to_string());
    }

    if pattern.len() > MAX_CUSTOM_PATTERN_LEN {
        return Err(format!(
            "Custom pattern exceeds {} characters",
            MAX_CUSTOM_PATTERN_LEN
        ));
    }

    let alternations = pattern.matches('|').count();
    if alternations > MAX_ALTERNATIONS {
        return Err(format!(
            "Custom pattern has too many alternations (max {})",
            MAX_ALTERNATIONS
        ));
    }

    let quantifiers = pattern
        .chars()
        .filter(|ch| matches!(ch, '*' | '+' | '?'))
        .count()
        + pattern.matches('{').count();
    if quantifiers > MAX_QUANTIFIERS {
        return Err(format!(
            "Custom pattern has too many quantifiers (max {})",
            MAX_QUANTIFIERS
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compile_patterns() {
        let config = PIIConfig::default();
        let compiled = compile_patterns(&config).unwrap();

        // Should have patterns for all enabled types
        assert!(!compiled.patterns.is_empty());
        assert!(!compiled.regex_set.is_empty());
    }

    #[test]
    fn test_ssn_pattern() {
        let config = PIIConfig {
            detect_ssn: true,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let text = "My SSN is 123-45-6789";
        let matches: Vec<_> = compiled.regex_set.matches(text).into_iter().collect();

        assert!(!matches.is_empty());
    }

    #[test]
    fn test_invalid_ssn_does_not_match_regex_set() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let text = "SSN: 000-12-3456";
        let matches: Vec<_> = compiled.regex_set.matches(text).into_iter().collect();

        assert!(matches.is_empty());
    }

    #[test]
    fn test_valid_ssn_in_656_to_699_range_matches_regex_set() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let text = "SSN: 667-12-3456";
        let matches: Vec<_> = compiled.regex_set.matches(text).into_iter().collect();

        assert!(!matches.is_empty());
    }

    #[test]
    fn test_empty_regex_set_when_all_detectors_disabled() {
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
            ..Default::default()
        };

        let compiled = compile_patterns(&config).unwrap();
        assert!(compiled.regex_set.is_empty());
        assert!(compiled.patterns.is_empty());
    }

    #[test]
    fn test_email_pattern() {
        let config = PIIConfig {
            detect_email: true,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let text = "Contact me at john.doe@example.com";
        let matches: Vec<_> = compiled.regex_set.matches(text).into_iter().collect();

        assert!(!matches.is_empty());
    }

    #[test]
    fn test_rejects_overly_complex_custom_pattern() {
        let mut config = PIIConfig::default();
        config.custom_patterns.push(super::super::config::CustomPattern {
            pattern: "(foo|bar|baz|qux|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen)".to_string(),
            description: "Too many branches".to_string(),
            mask_strategy: MaskingStrategy::Redact,
            enabled: true,
        });

        let err = compile_patterns(&config).err().unwrap();
        assert!(err.contains("too many alternations"));
    }

    #[test]
    fn test_accepts_escaped_literals_in_custom_pattern_complexity_check() {
        let mut config = PIIConfig::default();
        config
            .custom_patterns
            .push(super::super::config::CustomPattern {
                pattern: r"foo\|bar\+\?\{baz\}".to_string(),
                description: "Escaped regex metacharacters".to_string(),
                mask_strategy: MaskingStrategy::Redact,
                enabled: true,
            });

        let compiled = compile_patterns(&config);
        assert!(compiled.is_ok());
    }
}
