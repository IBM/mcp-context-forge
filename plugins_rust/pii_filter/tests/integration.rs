//! Integration tests covering the public Rust API without crossing the PyO3 boundary.
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use pii_filter_rust::config::{CustomPattern, MaskingStrategy, PIIConfig, PIIType};
use pii_filter_rust::detector::detect_pii;
use pii_filter_rust::masking::mask_pii;
use pii_filter_rust::patterns::compile_patterns;

use proptest::prelude::*;

#[test]
fn test_detect_and_mask_round_trip() {
    let config = PIIConfig::default();
    let patterns = compile_patterns(&config).unwrap();
    let text = "My SSN is 123-45-6789 and email: john@example.com";
    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.contains_key(&PIIType::Ssn));
    assert!(detections.contains_key(&PIIType::Email));
    let masked = mask_pii(text, &detections, &config).unwrap();
    assert!(!masked.as_ref().contains("123-45-6789"));
    assert!(!masked.as_ref().contains("john@example.com"));
    assert!(masked.as_ref().contains("***") || masked.as_ref().contains("[REDACTED]"));
}

#[test]
fn test_whitelist_excludes_match() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_credit_card: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_email: true,
        whitelist_patterns: vec!["john@example\\.com".to_string()],
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    // Only include the whitelisted email to ensure the detection map is empty.
    let text = "email: john@example.com";

    let detections = detect_pii(text, &patterns, &config);
    assert!(!detections.contains_key(&PIIType::Email));
}

#[test]
fn test_custom_pattern_detects_and_masks() {
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
        custom_patterns: vec![CustomPattern {
            pattern: r"\b\d{5}\b".to_string(),
            description: "ZIP".to_string(),
            mask_strategy: MaskingStrategy::Redact,
            enabled: true,
        }],
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "ZIP 12345";

    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.contains_key(&PIIType::Custom));
    assert_eq!(detections[&PIIType::Custom][0].value, "12345");

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert!(!masked.as_ref().contains("12345"));
    assert!(masked.as_ref().contains("[REDACTED]"));
}

#[test]
fn test_bsn_requires_elfproef() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_credit_card: false,
        detect_email: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_bsn: true,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let ok = detect_pii("BSN: 111222333", &patterns, &config);
    assert!(ok.contains_key(&PIIType::Bsn));

    let bad = detect_pii("BSN: 111222334", &patterns, &config);
    assert!(!bad.contains_key(&PIIType::Bsn));
}

#[test]
fn test_bsn_does_not_match_generic_order_or_invoice_ids() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_credit_card: false,
        detect_email: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_bsn: true,
        ..Default::default()
    };
    let patterns = compile_patterns(&config).unwrap();

    assert!(!detect_pii("Order: 100000009", &patterns, &config).contains_key(&PIIType::Bsn));
    assert!(!detect_pii("Invoice #100000009", &patterns, &config).contains_key(&PIIType::Bsn));
}

#[test]
fn test_credit_card_requires_luhn() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_email: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_credit_card: true,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();

    let ok = detect_pii("card: 4111 1111 1111 1111", &patterns, &config);
    assert!(ok.contains_key(&PIIType::CreditCard));

    let bad = detect_pii("card: 4111 1111 1111 1112", &patterns, &config);
    assert!(!bad.contains_key(&PIIType::CreditCard));
}

#[test]
fn test_phone_requires_libphonenumber_validation() {
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
        detect_full_name: false,
        detect_street_address: false,
        detect_us_zip_code: false,
        detect_us_ein: false,
        detect_us_itin: false,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();

    assert!(
        detect_pii("Call me at +442083661177", &patterns, &config).contains_key(&PIIType::Phone)
    );
    assert!(detect_pii("Office: (650) 253-0000", &patterns, &config).contains_key(&PIIType::Phone));
    assert!(
        !detect_pii("Order number: 123-456-7890", &patterns, &config).contains_key(&PIIType::Phone)
    );
}

#[test]
fn test_iban_detects_without_label_and_requires_checksum() {
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
        detect_full_name: false,
        detect_street_address: false,
        detect_us_zip_code: false,
        detect_us_ein: false,
        detect_us_itin: false,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();

    let valid = detect_pii("Wire to DE89370400440532013000", &patterns, &config);
    assert!(valid.contains_key(&PIIType::BankAccount));

    let invalid = detect_pii("Wire to DE00370400440532013000", &patterns, &config);
    assert!(!invalid.contains_key(&PIIType::BankAccount));
}

#[test]
fn test_us_aba_routing_detects_without_label_and_requires_checksum() {
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

    let patterns = compile_patterns(&config).unwrap();

    let valid = detect_pii("Routing 021000021", &patterns, &config);
    assert!(valid.contains_key(&PIIType::UsAbaRoutingNumber));

    let invalid = detect_pii("Routing 121000022", &patterns, &config);
    assert!(!invalid.contains_key(&PIIType::UsAbaRoutingNumber));
}

#[test]
fn test_no_pii_returns_original_text() {
    let config = PIIConfig::default();
    let patterns = compile_patterns(&config).unwrap();
    let text = "nothing sensitive here";

    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.is_empty());

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert_eq!(masked.as_ref(), text);
}

#[test]
fn test_ipv6_detects_compressed_forms() {
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
    let patterns = compile_patterns(&config).unwrap();

    let detections = detect_pii("Host: 2001:db8::1", &patterns, &config);
    assert!(detections.contains_key(&PIIType::IpAddress));

    let masked = mask_pii("Host: 2001:db8::1", &detections, &config).unwrap();
    assert!(!masked.as_ref().contains("2001:db8::1"));
}

#[test]
fn test_all_detectors_disabled_returns_no_matches() {
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
        ..Default::default()
    };
    let patterns = compile_patterns(&config).unwrap();

    let detections = detect_pii("SSN 123-45-6789 email john@example.com", &patterns, &config);
    assert!(detections.is_empty());
}

#[test]
fn test_unicode_and_emoji_text_detects_email_without_panicking() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_credit_card: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_email: true,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "emoji 😀 contact test@example.com مرحبا";
    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.contains_key(&PIIType::Email));
}

#[test]
fn test_multiple_pii_types_integration() {
    let config = PIIConfig {
        detect_credit_card: false,
        detect_bsn: false,
        detect_email: true,
        detect_ssn: true,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN 123-45-6789 and email: john@example.com";

    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.contains_key(&PIIType::Ssn));
    assert!(detections.contains_key(&PIIType::Email));

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert!(!masked.as_ref().contains("123-45-6789"));
    assert!(!masked.as_ref().contains("john@example.com"));
}

#[test]
fn test_driver_license_detects_top_four_states() {
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
    let patterns = compile_patterns(&config).unwrap();
    let samples = [
        ("CA Driver License: A1234567", "A1234567"),
        ("Texas DL: 12345678", "12345678"),
        ("Driver License Florida: F123456789012", "F123456789012"),
        ("NY License: 123456789", "123456789"),
        ("CA A1234567", "A1234567"),
        ("Texas 12345678", "12345678"),
        ("Florida F123456789012", "F123456789012"),
        ("NY 123456789", "123456789"),
    ];

    for (text, license_value) in samples {
        let detections = detect_pii(text, &patterns, &config);
        assert!(detections.contains_key(&PIIType::DriverLicense));

        let masked = mask_pii(text, &detections, &config).unwrap();
        assert!(!masked.as_ref().contains(license_value));
    }
}

#[test]
fn test_contextual_patterns_mask_only_the_secret_value() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: true,
        detect_credit_card: false,
        detect_email: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: true,
        detect_bank_account: false,
        detect_medical_record: false,
        ..Default::default()
    };
    let patterns = compile_patterns(&config).unwrap();
    let text = "BSN: 111222333 and passport no: AB1234567";

    let detections = detect_pii(text, &patterns, &config);
    assert_eq!(detections[&PIIType::Bsn][0].value, "111222333");
    assert_eq!(detections[&PIIType::Passport][0].value, "AB1234567");

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert!(masked.as_ref().contains("BSN: "));
    assert!(masked.as_ref().contains("passport no: "));
    assert!(!masked.as_ref().contains("111222333"));
    assert!(!masked.as_ref().contains("AB1234567"));
}

#[test]
fn test_passport_detects_only_supported_us_and_eu_formats() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_credit_card: false,
        detect_email: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: true,
        detect_bank_account: false,
        detect_medical_record: false,
        ..Default::default()
    };
    let patterns = compile_patterns(&config).unwrap();
    let samples = [
        ("passport number: 123456789", "123456789"),
        ("passport no: AB1234567", "AB1234567"),
        ("US 123456789", "123456789"),
        ("EU AB1234567", "AB1234567"),
    ];

    for (text, passport_value) in samples {
        let detections = detect_pii(text, &patterns, &config);
        assert!(detections.contains_key(&PIIType::Passport));
        assert_eq!(detections[&PIIType::Passport][0].value, passport_value);

        let masked = mask_pii(text, &detections, &config).unwrap();
        assert!(!masked.as_ref().contains(passport_value));
    }

    assert!(
        !detect_pii("passport no: ABC123456", &patterns, &config).contains_key(&PIIType::Passport)
    );
}

#[test]
fn test_new_labeled_detectors_detect_and_mask_only_sensitive_values() {
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
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = concat!(
        "Full Name: Jane Doe; ",
        "Address: 123 Main Street, Springfield, IL 62704; ",
        "Routing: 021000021; ",
        "ZIP Code: 94105-1234; ",
        "EIN: 12-3456789; ",
        "ITIN: 900-70-0001"
    );

    let detections = detect_pii(text, &patterns, &config);
    assert!(detections.contains_key(&PIIType::FullName));
    assert!(detections.contains_key(&PIIType::StreetAddress));
    assert!(detections.contains_key(&PIIType::UsAbaRoutingNumber));
    assert!(detections.contains_key(&PIIType::UsZipCode));
    assert!(detections.contains_key(&PIIType::UsEin));
    assert!(detections.contains_key(&PIIType::UsItin));

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert!(masked.as_ref().contains("Full Name: "));
    assert!(masked.as_ref().contains("Address: "));
    assert!(masked.as_ref().contains("Routing: "));
    assert!(masked.as_ref().contains("ZIP Code: "));
    assert!(masked.as_ref().contains("EIN: "));
    assert!(masked.as_ref().contains("ITIN: "));
    assert!(!masked.as_ref().contains("Jane Doe"));
    assert!(
        !masked
            .as_ref()
            .contains("123 Main Street, Springfield, IL 62704")
    );
    assert!(!masked.as_ref().contains("021000021"));
    assert!(!masked.as_ref().contains("94105-1234"));
    assert!(!masked.as_ref().contains("12-3456789"));
    assert!(!masked.as_ref().contains("900-70-0001"));
}

#[test]
fn test_contextual_ssn_masks_only_number_not_label() {
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
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN: 123456789";

    let detections = detect_pii(text, &patterns, &config);
    assert_eq!(detections[&PIIType::Ssn][0].value, "123456789");

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert_eq!(masked.as_ref(), "SSN: ***-**-6789");
}

#[test]
fn test_whitelist_matching_is_case_insensitive() {
    let config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_credit_card: false,
        detect_email: true,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        whitelist_patterns: vec!["john@example\\.com".to_string()],
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();

    let detections = detect_pii("Email: JOHN@EXAMPLE.COM", &patterns, &config);
    assert!(!detections.contains_key(&PIIType::Email));
}

#[test]
fn test_disabled_custom_pattern_does_not_detect() {
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
        custom_patterns: vec![CustomPattern {
            pattern: r"\bZIP-\d{5}\b".to_string(),
            description: "Disabled ZIP token".to_string(),
            mask_strategy: MaskingStrategy::Redact,
            enabled: false,
        }],
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let detections = detect_pii("Ship to ZIP-90210", &patterns, &config);
    assert!(detections.is_empty());
}

#[test]
fn test_hash_and_tokenize_masking_work_in_end_to_end_flow() {
    let base_config = PIIConfig {
        detect_ssn: false,
        detect_bsn: false,
        detect_credit_card: false,
        detect_email: true,
        detect_phone: false,
        detect_ip_address: false,
        detect_date_of_birth: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        ..Default::default()
    };
    let text = "Email: john@example.com";

    let hash_patterns = compile_patterns(&PIIConfig {
        default_mask_strategy: MaskingStrategy::Hash,
        ..base_config.clone()
    })
    .unwrap();
    let hash_detections = detect_pii(
        text,
        &hash_patterns,
        &PIIConfig {
            default_mask_strategy: MaskingStrategy::Hash,
            ..base_config.clone()
        },
    );
    let hash_masked = mask_pii(
        text,
        &hash_detections,
        &PIIConfig {
            default_mask_strategy: MaskingStrategy::Hash,
            ..base_config.clone()
        },
    )
    .unwrap();
    assert!(hash_masked.as_ref().contains("[HASH:"));
    assert!(!hash_masked.as_ref().contains("john@example.com"));

    let tokenize_patterns = compile_patterns(&PIIConfig {
        default_mask_strategy: MaskingStrategy::Tokenize,
        ..base_config.clone()
    })
    .unwrap();
    let tokenize_detections = detect_pii(
        text,
        &tokenize_patterns,
        &PIIConfig {
            default_mask_strategy: MaskingStrategy::Tokenize,
            ..base_config.clone()
        },
    );
    let tokenize_masked = mask_pii(
        text,
        &tokenize_detections,
        &PIIConfig {
            default_mask_strategy: MaskingStrategy::Tokenize,
            ..base_config
        },
    )
    .unwrap();
    assert!(tokenize_masked.as_ref().contains("[TOKEN:"));
    assert!(!tokenize_masked.as_ref().contains("john@example.com"));
}

#[test]
fn test_default_mode_keeps_reasonable_per_type_strategies() {
    let config = PIIConfig {
        detect_credit_card: false,
        detect_bsn: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_ssn: true,
        detect_date_of_birth: true,
        default_mask_strategy: MaskingStrategy::Auto,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN 123-45-6789 DOB 01/15/1990";
    let detections = detect_pii(text, &patterns, &config);

    assert_eq!(
        detections[&PIIType::Ssn][0].mask_strategy,
        MaskingStrategy::Partial
    );
    assert_eq!(
        detections[&PIIType::DateOfBirth][0].mask_strategy,
        MaskingStrategy::Redact
    );
}

#[test]
fn test_explicit_default_mask_strategy_overrides_all_detections() {
    let config = PIIConfig {
        detect_credit_card: false,
        detect_bsn: false,
        detect_phone: false,
        detect_ip_address: false,
        detect_passport: false,
        detect_bank_account: false,
        detect_medical_record: false,
        detect_ssn: true,
        detect_email: true,
        default_mask_strategy: MaskingStrategy::Redact,
        ..Default::default()
    };

    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN 123-45-6789 email john@example.com";
    let detections = detect_pii(text, &patterns, &config);

    assert_eq!(
        detections[&PIIType::Ssn][0].mask_strategy,
        MaskingStrategy::Redact
    );
    assert_eq!(
        detections[&PIIType::Email][0].mask_strategy,
        MaskingStrategy::Redact
    );

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert_eq!(masked.as_ref(), "SSN [REDACTED] email [REDACTED]");
}

#[test]
fn test_mask_uses_config_override_even_if_detection_payload_is_stale() {
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
        default_mask_strategy: MaskingStrategy::Remove,
        ..Default::default()
    };

    let text = "SSN: 123-45-6789";
    let mut detections = std::collections::HashMap::new();
    detections.insert(
        PIIType::Ssn,
        vec![pii_filter_rust::detector::Detection {
            value: "123-45-6789".to_string(),
            start: 5,
            end: 16,
            mask_strategy: MaskingStrategy::Partial,
            description: String::new(),
        }],
    );

    let masked = mask_pii(text, &detections, &config).unwrap();
    assert_eq!(masked.as_ref(), "SSN: ");
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(100))]

    #[test]
    fn test_prop_mask_ssn_removes_detected_value(
        a in 1u32..666,
        b in 1u32..100,
        c in 1u32..10000
    ) {
        let ssn = format!("{:03}-{:02}-{:04}", a, b, c);
        let text = format!("SSN: {ssn}");

        let config = PIIConfig {
            detect_bsn: false,
            detect_credit_card: false,
            detect_email: false,
            detect_phone: false,
            detect_ip_address: false,
            detect_date_of_birth: false,
            detect_passport: false,
            detect_bank_account: false,
            detect_medical_record: false,
            detect_ssn: true,
            ..Default::default()
        };

        let patterns = compile_patterns(&config).unwrap();
        let detections = detect_pii(&text, &patterns, &config);
        prop_assert!(detections.contains_key(&PIIType::Ssn));

        let masked = mask_pii(&text, &detections, &config).unwrap();
        prop_assert!(!masked.as_ref().contains(&ssn));
    }
}
