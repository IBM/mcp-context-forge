// SPDX-License-Identifier: Apache-2.0
//! Regex pattern compilation for PII detection; uses RegexSet for parallel matching.

use regex::{Regex, RegexSet, RegexSetBuilder};
use std::sync::LazyLock;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::error::PatternError;

/// Compiled pattern with metadata
#[derive(Debug, Clone)]
pub struct CompiledPattern {
    pub pii_type: PIIType,
    pub regex: Regex,
    pub mask_strategy: MaskingStrategy,
    pub description: String,
}

/// All compiled patterns with RegexSet for parallel matching
pub struct CompiledPatterns {
    pub regex_set: RegexSet,
    pub patterns: Vec<CompiledPattern>,
    pub whitelist: Vec<Regex>,
}

/// Pattern definitions (pattern, description, default mask strategy)
type PatternDef = (String, &'static str, MaskingStrategy);

// SSN patterns
static SSN_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    let formatted_ssn = r"\d{3}-\d{2}-\d{4}";
    let plain_ssn = r"\d{9}";
    vec![
        (
            formatted_ssn.to_string(),
            "US Social Security Number",
            MaskingStrategy::Partial,
        ),
        (
            format!(
                r"\b(?:ssn|social\s+security(?:\s+number)?)\s*[:=#]?\s*({}|{})\b",
                formatted_ssn, plain_ssn
            ),
            "US Social Security Number with context",
            MaskingStrategy::Partial,
        ),
    ]
});

// BSN patterns (Dutch Burgerservicenummer)
// Match 9-digit numbers with BSN context keywords to avoid false positives.
// All BSN candidates are validated with the elfproef (11-check) before reporting.
// Positive context: BSN, Citizen ID, Burgerservicenummer.
// Standard display format is 4.2.3 digits (e.g. 1112.22.333) per Dutch convention.
static BSN_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![
        (
            r"\b(?:BSN|Citizen\s+ID|Burgerservicenummer)[:\s#]*([0-9]{9})\b".to_string(),
            "Dutch BSN with explicit context",
            MaskingStrategy::Partial,
        ),
        (
            r"\b(?:BSN|Citizen\s+ID|Burgerservicenummer)[:\s#]*([0-9]{4}[.\s][0-9]{2}[.\s][0-9]{3})\b".to_string(),
            "Dutch BSN dotted format (4.2.3)",
            MaskingStrategy::Partial,
        ),
        (
            r"\b(?:My\s+)?BSN\s+(?:is\s+)?([0-9]{9})\b".to_string(),
            "BSN with 'is' context",
            MaskingStrategy::Partial,
        ),
        (
            r"\b(?:My\s+)?BSN\s+(?:is\s+)?([0-9]{4}[.\s][0-9]{2}[.\s][0-9]{3})\b".to_string(),
            "BSN dotted format with 'is' context",
            MaskingStrategy::Partial,
        ),
    ]
});

// Credit card patterns
static CREDIT_CARD_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b".to_string(),
        "Credit card number",
        MaskingStrategy::Partial,
    )]
});

// Email patterns
static EMAIL_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b".to_string(),
        "Email address",
        MaskingStrategy::Partial,
    )]
});

// Phone patterns (US and international)
static PHONE_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"(?:^|[^A-Za-z0-9_])((?:\+?\d[\d().\-\s]{6,}\d))\b".to_string(),
        "Phone number candidate",
        MaskingStrategy::Partial,
    )]
});

// IPv4 octet subpattern (0-255). Full IPv4 pattern is \b(?:OCTET\.){3}OCTET\b (no ReDoS; regex crate is non-backtracking).
const IPV4_OCTET: &str = r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)";

static IPV6_PATTERN: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"(?:^|[^A-Fa-f0-9:])((?:(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}|(?:[A-Fa-f0-9]{1,4}:){1,7}:|(?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4}|(?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}|(?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}|(?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}|(?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}|[A-Fa-f0-9]{1,4}:(?:(?::[A-Fa-f0-9]{1,4}){1,6})|:(?:(?::[A-Fa-f0-9]{1,4}){1,7}|:)))(?:$|[^A-Fa-f0-9:])".to_string(),
        "IPv6 address",
        MaskingStrategy::Redact,
    )]
});

// Date of birth patterns
static DOB_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    let birth_context = r"(?:DOB|D\.O\.B\.|Date\s+of\s+Birth|Birth\s*Date|Birthdate|Born|Birthday)";
    vec![
        (
            format!(
                r"\b{}\s*[:=#]?\s*([0-9]{{1,2}}[-/][0-9]{{1,2}}[-/][0-9]{{2,4}})\b",
                birth_context
            ),
            "Date of birth with numeric format",
            MaskingStrategy::Redact,
        ),
        (
            format!(
                r"\b{}\s*[:=#]?\s*((?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+[0-9]{{1,2}},?\s+[0-9]{{2,4}})\b",
                birth_context
            ),
            "Date of birth with month-name format",
            MaskingStrategy::Redact,
        ),
    ]
});

// Passport patterns
static PASSPORT_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![
        (
            r#"\b(?:passport(?:\s*(?:no|number))?|pp#?)\s*[:=]?\s*['"]?(\d{9})['"]?\b"#.to_string(),
            "U.S. passport number with context",
            MaskingStrategy::Redact,
        ),
        (
            r#"\b(?:passport(?:\s*(?:no|number))?|pp#?)\s*[:=]?\s*['"]?([A-Z]{2}\d{7})['"]?\b"#
                .to_string(),
            "EU-style passport number with context",
            MaskingStrategy::Redact,
        ),
        (
            r#"\b(?:US|U\.S\.|USA|United\s+States)\s*[:=#-]?\s*['"]?(\d{9})['"]?\b"#.to_string(),
            "U.S. passport number with country context",
            MaskingStrategy::Redact,
        ),
        (
            r#"\b(?:EU|European\s+Union)\s*[:=#-]?\s*['"]?([A-Z]{2}\d{7})['"]?\b"#.to_string(),
            "EU-style passport number with region context",
            MaskingStrategy::Redact,
        ),
    ]
});

fn stateful_driver_license_pattern(state_pattern: &str, number_pattern: &str) -> String {
    format!(
        r"\b(?:(?:{state_pattern})\s+(?:driver'?s?\s+license|dl|license)|(?:driver'?s?\s+license|dl|license)\s+(?:{state_pattern}))\s*[:=#]?\s*({number_pattern})\b"
    )
}

fn stateful_identifier_pattern(state_pattern: &str, number_pattern: &str) -> String {
    format!(r"\b(?:{state_pattern})\s*[:=#-]?\s*({number_pattern})\b")
}

// Driver license patterns for the four largest U.S. states by population.
// Require both a license label and an explicit state reference to keep the
// detector narrower than the old generic alphanumeric matcher.
static DRIVER_LICENSE_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![
        (
            stateful_driver_license_pattern(r"(?:CA|California)", r"[A-Z]\d{7}"),
            "California driver license number",
            MaskingStrategy::Redact,
        ),
        (
            stateful_identifier_pattern(r"(?:CA|California)", r"[A-Z]\d{7}"),
            "California driver license number with state context",
            MaskingStrategy::Redact,
        ),
        (
            stateful_driver_license_pattern(r"(?:TX|Texas)", r"\d{8}"),
            "Texas driver license number",
            MaskingStrategy::Redact,
        ),
        (
            stateful_identifier_pattern(r"(?:TX|Texas)", r"\d{8}"),
            "Texas driver license number with state context",
            MaskingStrategy::Redact,
        ),
        (
            stateful_driver_license_pattern(r"(?:FL|Florida)", r"[A-Z]\d{12}"),
            "Florida driver license number",
            MaskingStrategy::Redact,
        ),
        (
            stateful_identifier_pattern(r"(?:FL|Florida)", r"[A-Z]\d{12}"),
            "Florida driver license number with state context",
            MaskingStrategy::Redact,
        ),
        (
            stateful_driver_license_pattern(r"(?:NY|New\s+York)", r"\d{9}"),
            "New York driver license number",
            MaskingStrategy::Redact,
        ),
        (
            stateful_identifier_pattern(r"(?:NY|New\s+York)", r"\d{9}"),
            "New York driver license number with state context",
            MaskingStrategy::Redact,
        ),
    ]
});

// Bank account patterns
static BANK_ACCOUNT_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![
        (
            r#"\b(?:account|acct|iban|routing|sort\s*code)\s*(?:number|no|#)?\s*[:=]?\s*['"]?([0-9]{8,17})['"]?\b"#.to_string(),
            "Bank account number with context",
            MaskingStrategy::Redact,
        ),
        (
            r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b".to_string(),
            "IBAN",
            MaskingStrategy::Partial,
        ),
    ]
});

// Medical record patterns
static MEDICAL_RECORD_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:MRN|Medical Record)[#:\s]+([A-Z0-9]{6,12})\b".to_string(),
        "Medical record number",
        MaskingStrategy::Redact,
    )]
});

static FULL_NAME_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:full\s+name|customer\s+name|employee\s+name|patient\s+name|contact\s+name)\s*[:=]\s*([A-Za-z][A-Za-z'.-]+(?:\s+[A-Za-z][A-Za-z'.-]+){1,3})\b".to_string(),
        "Labeled full name",
        MaskingStrategy::Partial,
    )]
});

static STREET_ADDRESS_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:address|street\s+address|billing\s+address|shipping\s+address|home\s+address)\s*[:=]\s*(\d{1,6}\s+[A-Za-z0-9'.-]+(?:\s+[A-Za-z0-9'.-]+){0,5}\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl|terrace|ter)\b(?:,\s*[A-Za-z][A-Za-z .'-]+)*(?:\s+\d{5}(?:-\d{4})?)?)".to_string(),
        "Labeled street address",
        MaskingStrategy::Redact,
    )]
});

static US_ABA_ROUTING_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(\d{9})\b".to_string(),
        "U.S. ABA routing transit number",
        MaskingStrategy::Partial,
    )]
});

static US_ZIP_CODE_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:zip|zip\s+code)\s*[:=#]?\s*(\d{5}(?:-\d{4})?)\b".to_string(),
        "Labeled US ZIP code",
        MaskingStrategy::Partial,
    )]
});

static US_EIN_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:ein|employer\s+identification\s+number)\s*[:=#]?\s*(\d{2}-?\d{7})\b".to_string(),
        "Labeled U.S. employer identification number",
        MaskingStrategy::Partial,
    )]
});

static US_ITIN_PATTERNS: LazyLock<Vec<PatternDef>> = LazyLock::new(|| {
    vec![(
        r"\b(?:itin|individual\s+taxpayer\s+identification\s+number)\s*[:=#]?\s*(9\d{2}-?(7\d|8[0-8]|9[0-2]|9[4-9])-?\d{4})\b".to_string(),
        "Labeled U.S. individual taxpayer identification number",
        MaskingStrategy::Partial,
    )]
});

/// Compile patterns based on configuration
pub fn compile_patterns(config: &PIIConfig) -> Result<CompiledPatterns, PatternError> {
    let mut pattern_strings = Vec::new();
    let mut patterns = Vec::new();

    // Helper macro to add patterns with case-insensitive matching (match Python behavior)
    macro_rules! add_patterns {
        ($enabled:expr, $pii_type:expr, $pattern_list:expr) => {
            if $enabled {
                for (pattern, description, mask_strategy) in $pattern_list.iter() {
                    pattern_strings.push(pattern.clone());
                    let regex = regex::RegexBuilder::new(pattern)
                        .case_insensitive(true)
                        .build()
                        .map_err(|e| PatternError::RegexCompile {
                            pattern: pattern.clone(),
                            source: e,
                        })?;
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
    add_patterns!(config.detect_bsn, PIIType::Bsn, &*BSN_PATTERNS);
    add_patterns!(
        config.detect_credit_card,
        PIIType::CreditCard,
        &*CREDIT_CARD_PATTERNS
    );
    add_patterns!(config.detect_email, PIIType::Email, &*EMAIL_PATTERNS);
    add_patterns!(config.detect_phone, PIIType::Phone, &*PHONE_PATTERNS);
    if config.detect_ip_address {
        let ipv4_pattern = format!(r"\b(?:{}\.){{3}}{}\b", IPV4_OCTET, IPV4_OCTET);
        pattern_strings.push(ipv4_pattern.clone());
        let regex = regex::RegexBuilder::new(&ipv4_pattern)
            .case_insensitive(true)
            .build()
            .map_err(|e| PatternError::RegexCompile {
                pattern: ipv4_pattern.clone(),
                source: e,
            })?;
        patterns.push(CompiledPattern {
            pii_type: PIIType::IpAddress,
            regex,
            mask_strategy: MaskingStrategy::Redact,
            description: "IPv4 address".to_string(),
        });
        for (pattern, description, mask_strategy) in IPV6_PATTERN.iter() {
            pattern_strings.push(pattern.clone());
            let regex = regex::RegexBuilder::new(pattern)
                .case_insensitive(true)
                .build()
                .map_err(|e| PatternError::RegexCompile {
                    pattern: pattern.clone(),
                    source: e,
                })?;
            patterns.push(CompiledPattern {
                pii_type: PIIType::IpAddress,
                regex,
                mask_strategy: *mask_strategy,
                description: description.to_string(),
            });
        }
    }
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
    add_patterns!(
        config.detect_full_name,
        PIIType::FullName,
        &*FULL_NAME_PATTERNS
    );
    add_patterns!(
        config.detect_street_address,
        PIIType::StreetAddress,
        &*STREET_ADDRESS_PATTERNS
    );
    add_patterns!(
        config.detect_us_aba_routing_number,
        PIIType::UsAbaRoutingNumber,
        &*US_ABA_ROUTING_PATTERNS
    );
    add_patterns!(
        config.detect_us_zip_code,
        PIIType::UsZipCode,
        &*US_ZIP_CODE_PATTERNS
    );
    add_patterns!(config.detect_us_ein, PIIType::UsEin, &*US_EIN_PATTERNS);
    add_patterns!(config.detect_us_itin, PIIType::UsItin, &*US_ITIN_PATTERNS);
    // Add custom patterns
    for custom in &config.custom_patterns {
        if custom.enabled {
            pattern_strings.push(custom.pattern.clone());
            let regex = regex::RegexBuilder::new(&custom.pattern)
                .case_insensitive(true)
                .build()
                .map_err(|e| PatternError::RegexCompile {
                    pattern: custom.pattern.clone(),
                    source: e,
                })?;
            patterns.push(CompiledPattern {
                pii_type: PIIType::Custom,
                regex,
                mask_strategy: custom.mask_strategy,
                description: custom.description.clone(),
            });
        }
    }

    // Compile whitelist patterns with error checking and case-insensitive (match Python behavior)
    let mut whitelist = Vec::new();
    for (idx, pattern) in config.whitelist_patterns.iter().enumerate() {
        match regex::RegexBuilder::new(pattern)
            .case_insensitive(true)
            .build()
        {
            Ok(regex) => whitelist.push(regex),
            Err(e) => {
                return Err(PatternError::WhitelistCompile {
                    pattern: format!("#{idx}: {pattern}"),
                    source: e,
                });
            }
        }
    }

    if pattern_strings.is_empty() {
        return Ok(CompiledPatterns {
            regex_set: RegexSet::empty(),
            patterns,
            whitelist,
        });
    }

    // Compile RegexSet for fast multi-pattern prefiltering.
    let regex_set = RegexSetBuilder::new(&pattern_strings)
        .case_insensitive(true)
        .build()
        .map_err(|e| PatternError::RegexSetCompile { source: e })?;

    Ok(CompiledPatterns {
        regex_set,
        patterns,
        whitelist,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::detector::detect_pii;

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

    #[test]
    fn test_phone_pattern_matches_plus_prefixed_numbers() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: true,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(
            compiled
                .regex_set
                .matches("+441234567890")
                .into_iter()
                .count()
                > 0
        );
        assert!(
            compiled
                .regex_set
                .matches("Call +15551234567")
                .into_iter()
                .count()
                > 0
        );
    }

    #[test]
    fn test_bank_account_requires_context() {
        // Only enable bank account so no other pattern (SSN, BSN, etc.) can match.
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: true,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let no_context = "invoice 123456789012 paid";
        assert!(compiled.regex_set.matches(no_context).into_iter().count() == 0);

        let with_context = "account number: 123456789012";
        assert!(compiled.regex_set.matches(with_context).into_iter().count() > 0);

        let iban = "DE89370400440532013000";
        assert!(compiled.regex_set.matches(iban).into_iter().count() > 0);
    }

    #[test]
    fn test_passport_supports_label_or_region_context() {
        let config = PIIConfig {
            detect_passport: true,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let no_context = "Order AB1234567 shipped";
        assert!(compiled.regex_set.matches(no_context).into_iter().count() == 0);

        let eu_with_context = "passport no: AB1234567";
        assert!(
            compiled
                .regex_set
                .matches(eu_with_context)
                .into_iter()
                .count()
                > 0
        );

        let us_with_context = "passport number: 123456789";
        assert!(
            compiled
                .regex_set
                .matches(us_with_context)
                .into_iter()
                .count()
                > 0
        );

        let eu_with_region = "EU AB1234567";
        assert!(
            compiled
                .regex_set
                .matches(eu_with_region)
                .into_iter()
                .count()
                > 0
        );

        let us_with_region = "US 123456789";
        assert!(
            compiled
                .regex_set
                .matches(us_with_region)
                .into_iter()
                .count()
                > 0
        );

        let unsupported_with_context = "passport no: ABC123456";
        assert!(
            compiled
                .regex_set
                .matches(unsupported_with_context)
                .into_iter()
                .count()
                == 0
        );
    }

    #[test]
    fn test_ipv4_pattern_does_not_match_non_dotted_numbers() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: true,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert_eq!(
            compiled
                .regex_set
                .matches("10x20x30x40")
                .into_iter()
                .count(),
            0
        );
        assert!(
            compiled
                .regex_set
                .matches("10.20.30.40")
                .into_iter()
                .count()
                > 0
        );
    }

    #[test]
    fn test_ipv6_pattern_matches_compressed_forms() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: true,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(compiled.regex_set.is_match("2001:db8::1"));
        assert!(compiled.regex_set.is_match("fe80::1"));
        assert!(compiled.regex_set.is_match("::1"));
        assert!(!compiled.regex_set.is_match("2001:::1"));
    }

    #[test]
    fn test_custom_pattern_invalid_regex_returns_regex_compile_error() {
        use super::super::config::CustomPattern;
        use super::super::error::PatternError;

        let config = PIIConfig {
            custom_patterns: vec![CustomPattern {
                pattern: "[[[".to_string(),
                description: "bad".to_string(),
                mask_strategy: MaskingStrategy::Redact,
                enabled: true,
            }],
            ..Default::default()
        };
        let result = compile_patterns(&config);
        assert!(
            matches!(result, Err(PatternError::RegexCompile { pattern, .. }) if pattern == "[[[")
        );
    }

    #[test]
    fn test_whitelist_invalid_regex_returns_whitelist_compile_error() {
        use super::super::error::PatternError;

        let config = PIIConfig {
            whitelist_patterns: vec!["[[[".to_string()],
            ..Default::default()
        };
        let result = compile_patterns(&config);
        assert!(
            matches!(result, Err(PatternError::WhitelistCompile { pattern, .. }) if pattern == "#0: [[[")
        );
    }

    #[test]
    fn test_custom_pattern_matches_and_yields_custom_type() {
        use super::super::config::CustomPattern;

        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            custom_patterns: vec![CustomPattern {
                pattern: r"\bZIP-?\d{5}\b".to_string(),
                description: "ZIP code".to_string(),
                mask_strategy: MaskingStrategy::Hash,
                enabled: true,
            }],
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();
        let text = "Ship to ZIP-90210 or ZIP 12345";
        let matches: Vec<_> = compiled.regex_set.matches(text).into_iter().collect();
        assert!(!matches.is_empty());
        let mut found_custom = false;
        for (idx, p) in compiled.patterns.iter().enumerate() {
            if matches.contains(&idx) && p.pii_type == PIIType::Custom {
                found_custom = true;
                break;
            }
        }
        assert!(found_custom);
    }

    #[test]
    fn test_new_detector_patterns_can_be_enabled_individually() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: true,
            detect_street_address: true,
            detect_us_aba_routing_number: true,
            detect_us_zip_code: true,
            detect_us_ein: true,
            detect_us_itin: true,
            detect_driver_license: true,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let samples = [
            "Full Name: Jane Doe",
            "Address: 123 Main Street, Springfield, IL 62704",
            "021000021",
            "ZIP Code: 94105-1234",
            "EIN: 12-3456789",
            "ITIN: 900-70-0001",
            "CA Driver License: A1234567",
        ];

        for sample in samples {
            assert!(
                compiled.regex_set.matches(sample).into_iter().count() > 0,
                "expected a compiled pattern match for {sample}"
            );
        }
    }

    #[test]
    fn test_ssn_patterns_require_valid_values_or_context() {
        let config = PIIConfig {
            detect_ssn: true,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(detect_pii("SSN: 123-45-6789", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(
            detect_pii("social security number 123456789", &compiled, &config)
                .contains_key(&PIIType::Ssn)
        );
        assert!(!detect_pii("order id 123456789", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(!detect_pii("SSN: 000-12-3456", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(!detect_pii("SSN: 666-12-3456", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(!detect_pii("SSN: 900-12-3456", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(!detect_pii("SSN: 123-00-3456", &compiled, &config).contains_key(&PIIType::Ssn));
        assert!(!detect_pii("SSN: 123-45-0000", &compiled, &config).contains_key(&PIIType::Ssn));
    }

    #[test]
    fn test_dob_patterns_require_birth_context() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: true,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(compiled.regex_set.is_match("DOB: 01/15/1990"));
        assert!(
            compiled
                .regex_set
                .is_match("Date of Birth: January 15, 1990")
        );
        assert!(compiled.regex_set.is_match("Born 1-15-90"));
        assert!(!compiled.regex_set.is_match("invoice date 01/15/1990"));
        assert!(!compiled.regex_set.is_match("created January 15, 1990"));
    }

    #[test]
    fn test_full_name_stays_context_only() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: true,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(compiled.regex_set.is_match("Full Name: Jane Doe"));
        assert!(!compiled.regex_set.is_match("Name: Project Phoenix"));
    }

    #[test]
    fn test_us_tax_patterns_are_label_and_state_specific() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: true,
            detect_us_itin: true,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(compiled.regex_set.is_match("EIN: 12-3456789"));
        assert!(!compiled.regex_set.is_match("tax id 123456789"));
        assert!(compiled.regex_set.is_match("ITIN: 900-70-0001"));
        assert!(!compiled.regex_set.is_match("ITIN: 123-45-6789"));
    }

    #[test]
    fn test_aba_routing_pattern_matches_unlabeled_nine_digits() {
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
            detect_full_name: false,
            detect_street_address: false,
            detect_us_aba_routing_number: true,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        assert!(compiled.regex_set.is_match("021000021"));
        assert!(!compiled.regex_set.is_match("0210000210"));
    }

    #[test]
    fn test_driver_license_patterns_support_state_context_without_license_label() {
        let config = PIIConfig {
            detect_ssn: false,
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_driver_license: true,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_full_name: false,
            detect_street_address: false,
            detect_us_zip_code: false,
            detect_us_ein: false,
            detect_us_itin: false,
            ..Default::default()
        };
        let compiled = compile_patterns(&config).unwrap();

        let samples = [
            "CA Driver License: A1234567",
            "Texas DL: 12345678",
            "Driver License Florida: F123456789012",
            "NY License: 123456789",
            "CA A1234567",
            "Texas 12345678",
            "Florida F123456789012",
            "NY 123456789",
        ];

        for sample in samples {
            assert!(
                compiled.regex_set.is_match(sample),
                "expected a driver license match for {sample}"
            );
        }

        assert!(!compiled.regex_set.is_match("Driver License: A1234567"));
        assert!(!compiled.regex_set.is_match("WA Driver License: W1234567"));
    }
}
