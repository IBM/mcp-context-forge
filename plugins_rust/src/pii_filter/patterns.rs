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
    pub mask_strategy: MaskingStrategy,
    #[allow(dead_code)]
    pub description: String,
}

/// All compiled patterns with RegexSet for parallel matching
pub struct CompiledPatterns {
    pub regex_set: RegexSet,
    pub patterns: Vec<CompiledPattern>,
    pub whitelist: Vec<Regex>,
}

/// Pattern definitions (pattern, description, default mask strategy)
type PatternDef = (&'static str, &'static str, MaskingStrategy);

// SSN patterns
static SSN_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b",
        "US Social Security Number",
        MaskingStrategy::Partial,
    )]
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
            r"\b\+[1-9]\d{9,14}\b",
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
        r"\b[A-Z]{1,2}\d{6,9}\b",
        "Passport number",
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
            r"\b\d{8,17}\b",
            "Bank account number",
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

// AWS key patterns
static AWS_KEY_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        (
            r"\bAKIA[0-9A-Z]{16}\b",
            "AWS Access Key ID",
            MaskingStrategy::Redact,
        ),
        (
            r"\b[A-Za-z0-9/+=]{40}\b",
            "AWS Secret Access Key",
            MaskingStrategy::Redact,
        ),
    ]
});

// API key patterns
static API_KEY_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![(
        r#"\b(?:api[_-]?key|apikey|api_token|access[_-]?token)[:\s]+['"]?[A-Za-z0-9\-_]{20,}['"]?\b"#,
        "Generic API key",
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
                        mask_strategy: *mask_strategy,
                        description: description.to_string(),
                    });
                }
            }
        };
    }

    // Add patterns based on config
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
    add_patterns!(config.detect_aws_keys, PIIType::AwsKey, &*AWS_KEY_PATTERNS);
    add_patterns!(config.detect_api_keys, PIIType::ApiKey, &*API_KEY_PATTERNS);

    // Add custom patterns
    for custom in &config.custom_patterns {
        if custom.enabled {
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
                mask_strategy: custom.mask_strategy,
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
}
