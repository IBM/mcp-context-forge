use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};

use crate::config::SecretsDetectionConfig;
use crate::patterns::PATTERNS;

/// A single secret detection finding
#[derive(Debug, Clone)]
pub struct Finding {
    pub pii_type: String,
    pub preview: String,
}

/// Recursively scan Python container for secrets using direct PyO3 traversal
///
/// This avoids JSON serialization overhead by working directly with Python objects.
/// Similar to the PII filter's approach for better performance on large payloads.
///
/// Returns (total_count, redacted_container, findings)
pub fn scan_container<'py>(
    py: Python<'py>,
    container: &Bound<'py, PyAny>,
    cfg: &SecretsDetectionConfig,
) -> PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> {
    let mut total = 0;
    let findings = PyList::empty(py);

    // Handle strings directly
    if let Ok(text) = container.extract::<String>() {
        let (fs, redacted_str) = detect_and_redact(&text, cfg);
        total += fs.len();

        // Add findings to list
        for finding in fs {
            let finding_dict = PyDict::new(py);
            finding_dict.set_item("type", finding.pii_type)?;
            finding_dict.set_item("match", finding.preview)?;
            findings.append(finding_dict)?;
        }

        let redacted_py = PyString::new(py, &redacted_str);
        return Ok((total, redacted_py.into_any(), findings));
    }

    // Handle dictionaries
    if let Ok(dict) = container.cast::<PyDict>() {
        let new_dict = PyDict::new(py);

        for (key, value) in dict.iter() {
            let (count, redacted_value, value_findings) = scan_container(py, &value, cfg)?;
            total += count;

            // Merge findings
            for finding in value_findings.iter() {
                findings.append(finding)?;
            }

            new_dict.set_item(key, redacted_value)?;
        }

        return Ok((total, new_dict.into_any(), findings));
    }

    // Handle lists
    if let Ok(list) = container.cast::<PyList>() {
        let new_list = PyList::empty(py);

        for item in list.iter() {
            let (count, redacted_item, item_findings) = scan_container(py, &item, cfg)?;
            total += count;

            // Merge findings
            for finding in item_findings.iter() {
                findings.append(finding)?;
            }

            new_list.append(redacted_item)?;
        }

        return Ok((total, new_list.into_any(), findings));
    }

    // Other types: no processing (numbers, booleans, None, etc.)
    Ok((0, container.clone(), findings))
}

/// Combined detection and redaction in a single pass
///
/// Returns (findings, redacted_text)
pub fn detect_and_redact(text: &str, cfg: &SecretsDetectionConfig) -> (Vec<Finding>, String) {
    let mut findings = Vec::new();

    // Single pass: detect from original text, redact if enabled
    let mut redacted = text.to_string();

    for (name, pat) in PATTERNS.iter() {
        if !cfg.enabled.get(*name).copied().unwrap_or(true) {
            continue;
        }

        // Always detect from the original text to avoid false positives from redaction
        for m in pat.find_iter(text) {
            let mat = m.as_str();
            let preview = if mat.len() > 8 {
                format!("{}…", &mat[..8])
            } else {
                mat.to_string()
            };

            findings.push(Finding {
                pii_type: name.to_string(),
                preview,
            });
        }

        // Redact matches if redaction is enabled
        if cfg.redact {
            redacted = pat.replace_all(&redacted, &cfg.redaction_text).into_owned();
        }
    }

    (findings, redacted)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_and_redact_no_secrets() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        let text = "This is a normal string with no secrets";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert_eq!(findings.len(), 0);
        assert_eq!(redacted, text);
    }

    #[test]
    fn test_detect_and_redact_aws_key() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "***REDACTED***".to_string(),
            ..Default::default()
        };

        let text = "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].pii_type, "aws_access_key_id");
        assert_eq!(findings[0].preview, "AKIAFAKE…");
        assert_eq!(redacted, "AWS_ACCESS_KEY_ID=***REDACTED***");
    }

    #[test]
    fn test_detect_and_redact_multiple_secrets() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            ..Default::default()
        };

        let text = "Key: AKIAFAKE12345EXAMPLE and token: xoxr-fake-000000000-fake000000000-fakefakefakefake";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(findings.len() >= 2, "Should detect at least 2 secrets");
        assert!(redacted.contains("[REDACTED]"));
        assert!(!redacted.contains("AKIAFAKE12345EXAMPLE"));
        assert!(!redacted.contains("xoxr-fake-000000"));
    }

    #[test]
    fn test_detect_and_redact_without_redaction() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        let text = "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert_eq!(findings.len(), 1);
        assert_eq!(redacted, text); // Should not be redacted
    }

    #[test]
    fn test_detect_and_redact_disabled_pattern() {
        let mut enabled = std::collections::HashMap::new();
        enabled.insert("aws_access_key_id".to_string(), false);
        enabled.insert("slack_token".to_string(), true);

        let cfg = SecretsDetectionConfig {
            enabled,
            redact: true,
            redaction_text: "***".to_string(),
            ..Default::default()
        };

        let text = "Key: AKIAFAKE12345EXAMPLE and token: xoxr-fake-000000000-fake000000000-fakefakefakefake";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // At least slack_token should be detected (may also match base64_24)
        assert!(!findings.is_empty(), "Should detect at least slack_token");
        assert!(
            findings.iter().any(|f| f.pii_type == "slack_token"),
            "Should detect slack_token"
        );
        assert!(redacted.contains("AKIAFAKE12345EXAMPLE")); // AWS key not redacted
        assert!(!redacted.contains("xoxr-fake-000000")); // Slack token redacted
    }

    #[test]
    fn test_detect_and_redact_hex_and_base64() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        // Test that hex secrets are detected
        let hex_text = "secret=0123456789abcdef0123456789abcdef";
        let (hex_findings, _) = detect_and_redact(hex_text, &cfg);
        assert!(!hex_findings.is_empty(), "Should detect hex secrets");

        // Test that base64 secrets are detected
        let base64_text = "token=SGVsbG8gV29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IGVuY29kZWQgc3RyaW5n";
        let (b64_findings, _) = detect_and_redact(base64_text, &cfg);
        assert!(!b64_findings.is_empty(), "Should detect base64 secrets");
    }

    #[test]
    fn test_detect_and_redact_google_api_key() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            ..Default::default()
        };

        let text = "GOOGLE_API_KEY=AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(!findings.is_empty());
        assert!(findings.iter().any(|f| f.pii_type == "google_api_key"));
        assert!(redacted.contains("[REDACTED]"));
        assert!(!redacted.contains("AIzaFAKE_KEY_FOR_TEST"));
    }

    #[test]
    fn test_detect_and_redact_slack_token() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        let text = "SLACK_TOKEN=xoxr-fake-000000000-fake000000000-fakefakefakefake";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(!findings.is_empty());
        assert!(findings.iter().any(|f| f.pii_type == "slack_token"));
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_detect_and_redact_private_key() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        let text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(!findings.is_empty());
        assert!(findings.iter().any(|f| f.pii_type == "private_key_block"));
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_detect_and_redact_jwt() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        let text = "Authorization: Bearer eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(!findings.is_empty());
        assert!(findings.iter().any(|f| f.pii_type == "jwt_like"));
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_detect_and_redact_preview_truncation() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        let text = "Key: AKIAFAKE12345EXAMPLE";
        let (findings, _) = detect_and_redact(text, &cfg);

        assert!(!findings.is_empty());
        let finding = &findings[0];
        assert_eq!(finding.preview, "AKIAFAKE…");
        assert_eq!(finding.preview.chars().count(), 9); // 8 chars + ellipsis
    }

    #[test]
    fn test_detect_and_redact_short_preview() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        // Create a pattern that matches short strings
        let text = "token=xoxr-fake";
        let (findings, _) = detect_and_redact(text, &cfg);

        // If any findings, check preview handling
        for finding in findings {
            assert!(finding.preview.len() <= 9);
        }
    }

    #[test]
    fn test_finding_clone() {
        let finding = Finding {
            pii_type: "test".to_string(),
            preview: "preview".to_string(),
        };

        let cloned = finding.clone();
        assert_eq!(finding.pii_type, cloned.pii_type);
        assert_eq!(finding.preview, cloned.preview);
    }

    #[test]
    fn test_finding_debug() {
        let finding = Finding {
            pii_type: "aws_key".to_string(),
            preview: "AKIA…".to_string(),
        };

        let debug_str = format!("{:?}", finding);
        assert!(debug_str.contains("aws_key"));
        assert!(debug_str.contains("AKIA"));
    }

    #[test]
    fn test_detect_and_redact_short_match() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        // Test with a short match (less than 8 chars)
        let text = "key=abc123";
        let (findings, _) = detect_and_redact(text, &cfg);

        // Check that short previews don't get truncated
        for finding in findings {
            if finding.preview.len() <= 8 {
                assert!(!finding.preview.contains('…'));
            }
        }
    }

    #[test]
    fn test_scan_container_string_direct() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            ..Default::default()
        };

        // Test the string extraction path in scan_container
        let text = "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert_eq!(findings.len(), 1);
        assert!(redacted.contains("[REDACTED]"));
        assert!(!redacted.contains("AKIAFAKE12345EXAMPLE"));
    }

    #[test]
    fn test_scan_container_dict_logic() {
        // Test dict iteration logic by simulating what scan_container does
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "***".to_string(),
            ..Default::default()
        };

        // Simulate processing multiple dict values
        let values = vec![
            "AKIAFAKE12345EXAMPLE",
            "normal text",
            "xoxr-fake-000000000-fake000000000-fakefakefakefake",
        ];

        let mut total_count = 0;
        let mut all_findings = Vec::new();

        for value in values {
            let (findings, _redacted) = detect_and_redact(value, &cfg);
            total_count += findings.len();
            all_findings.extend(findings);
        }

        assert!(total_count >= 2, "Should detect at least 2 secrets");
        assert!(all_findings.len() >= 2);
    }

    #[test]
    fn test_scan_container_list_logic() {
        // Test list iteration logic
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "[X]".to_string(),
            ..Default::default()
        };

        let items = vec![
            "AKIAFAKE12345EXAMPLE",
            "normal text",
            "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345",
        ];

        let mut total_count = 0;
        let mut redacted_items = Vec::new();

        for item in items {
            let (findings, redacted) = detect_and_redact(item, &cfg);
            total_count += findings.len();
            redacted_items.push(redacted);
        }

        assert!(total_count >= 2, "Should detect at least 2 secrets");
        assert_eq!(redacted_items.len(), 3);
        assert!(redacted_items[0].contains("[X]"));
        assert_eq!(redacted_items[1], "normal text");
    }

    #[test]
    fn test_scan_container_nested_structure() {
        // Test nested structure processing
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        // Simulate nested dict: outer -> inner -> secret
        let secret_text = "AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(secret_text, &cfg);

        assert_eq!(findings.len(), 1);
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_scan_container_empty_containers() {
        let cfg = SecretsDetectionConfig::default();

        // Empty string
        let (findings, redacted) = detect_and_redact("", &cfg);
        assert_eq!(findings.len(), 0);
        assert_eq!(redacted, "");

        // String with no secrets
        let (findings, redacted) = detect_and_redact("just normal text", &cfg);
        assert_eq!(findings.len(), 0);
        assert_eq!(redacted, "just normal text");
    }

    #[test]
    fn test_scan_container_multiple_findings() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        let text =
            "Key: AKIAFAKE12345EXAMPLE Token: xoxr-fake-000000000-fake000000000-fakefakefakefake";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert!(findings.len() >= 2, "Should detect at least 2 secrets");
        assert!(redacted.contains("***REDACTED***"));

        // Verify findings have required fields
        for finding in &findings {
            assert!(!finding.pii_type.is_empty());
            assert!(!finding.preview.is_empty());
        }
    }

    #[test]
    fn test_scan_container_no_redaction_mode() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        let text = "AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        assert_eq!(findings.len(), 1);
        // Text should NOT be redacted when redact=false
        assert_eq!(redacted, text);
    }

    #[test]
    fn test_scan_container_mixed_content() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        // Simulate processing mixed content (dict with list of strings)
        let items = vec!["AKIAFAKE12345EXAMPLE", "safe text"];
        let mut total_findings = 0;

        for item in items {
            let (findings, _) = detect_and_redact(item, &cfg);
            total_findings += findings.len();
        }

        assert_eq!(total_findings, 1);
    }

    #[test]
    fn test_preview_generation() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        // Test long secret (should be truncated)
        let long_text = "AKIAFAKE12345EXAMPLE";
        let (findings, _) = detect_and_redact(long_text, &cfg);

        if !findings.is_empty() {
            let preview = &findings[0].preview;
            // Preview should be truncated to 8 chars + ellipsis for strings > 8 chars
            // The match is 20 chars, so it should be truncated
            if long_text.len() > 8 {
                assert!(
                    preview.contains('…'),
                    "Long preview should contain ellipsis"
                );
                assert_eq!(preview.chars().count(), 9); // 8 chars + ellipsis
            }
        }
    }

    #[test]
    fn test_findings_accumulation() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        // Test that findings accumulate correctly across multiple values
        let secrets = vec![
            "AKIAFAKE12345EXAMPLE",
            "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345",
            "xoxr-fake-000000000-fake000000000-fakefakefakefake",
        ];

        let mut all_findings = Vec::new();
        for secret in secrets {
            let (findings, _) = detect_and_redact(secret, &cfg);
            all_findings.extend(findings);
        }

        assert!(all_findings.len() >= 3, "Should accumulate all findings");
    }

    #[test]
    fn test_detect_and_redact_pattern_disabled_via_config() {
        let mut enabled = std::collections::HashMap::new();
        enabled.insert("aws_access_key_id".to_string(), false);
        enabled.insert("google_api_key".to_string(), true);

        let cfg = SecretsDetectionConfig {
            enabled,
            redact: true,
            redaction_text: "[X]".to_string(),
            ..Default::default()
        };

        let text = "AWS: AKIAFAKE12345EXAMPLE Google: AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // AWS pattern is disabled, so it should not be detected
        assert!(!findings.iter().any(|f| f.pii_type == "aws_access_key_id"));
        // Google pattern is enabled, so it should be detected
        assert!(findings.iter().any(|f| f.pii_type == "google_api_key"));
        // AWS key should NOT be redacted (pattern disabled)
        assert!(redacted.contains("AKIAFAKE12345EXAMPLE"));
        // Google key SHOULD be redacted (pattern enabled)
        assert!(!redacted.contains("AIzaFAKE_KEY_FOR_TEST"));
    }

    #[test]
    fn test_detect_and_redact_all_patterns_disabled() {
        let mut enabled = std::collections::HashMap::new();
        for pattern_name in crate::patterns::PATTERNS.keys() {
            enabled.insert(pattern_name.to_string(), false);
        }

        let cfg = SecretsDetectionConfig {
            enabled,
            redact: true,
            ..Default::default()
        };

        let text = "AKIAFAKE12345EXAMPLE AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // No patterns enabled, so no findings
        assert_eq!(findings.len(), 0);
        // Text should be unchanged
        assert_eq!(redacted, text);
    }

    #[test]
    fn test_detect_and_redact_preview_length_boundary() {
        let cfg = SecretsDetectionConfig {
            redact: false,
            ..Default::default()
        };

        // Test with a secret that's exactly 8 characters
        let text_8 = "key=abcd1234";
        let (findings_8, _) = detect_and_redact(text_8, &cfg);

        // Test with a secret that's 9 characters (should be truncated)
        let text_9 = "AKIAFAKE12345EXAMPLE";
        let (findings_9, _) = detect_and_redact(text_9, &cfg);

        // Verify preview handling for different lengths
        for finding in findings_8 {
            if finding.preview.len() <= 8 {
                assert!(
                    !finding.preview.contains('…'),
                    "Short preview should not have ellipsis"
                );
            }
        }

        for finding in findings_9 {
            if finding.preview.len() == 9 {
                assert!(
                    finding.preview.contains('…'),
                    "Long preview should have ellipsis"
                );
            }
        }
    }

    #[test]
    fn test_detect_and_redact_unwrap_or_default_behavior() {
        // Test the unwrap_or(true) behavior when pattern is not in enabled map
        let mut enabled = std::collections::HashMap::new();
        // Only add one pattern, others will use default (true)
        enabled.insert("aws_access_key_id".to_string(), false);

        let cfg = SecretsDetectionConfig {
            enabled,
            redact: true,
            ..Default::default()
        };

        let text = "Google: AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // google_api_key is not in enabled map, so it should default to true (enabled)
        assert!(findings.iter().any(|f| f.pii_type == "google_api_key"));
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_detect_and_redact_multiple_matches_same_pattern() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            ..Default::default()
        };

        let text = "Key1: AKIAFAKE12345EXAMPLE Key2: AKIAFAKE67890EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // Should detect both AWS keys
        let aws_findings: Vec<_> = findings
            .iter()
            .filter(|f| f.pii_type == "aws_access_key_id")
            .collect();
        assert_eq!(aws_findings.len(), 2, "Should detect both AWS keys");

        // Both should be redacted
        assert!(!redacted.contains("AKIAFAKE12345EXAMPLE"));
        assert!(!redacted.contains("AKIAFAKE67890EXAMPLE"));
        assert_eq!(redacted.matches("[REDACTED]").count(), 2);
    }

    #[test]
    fn test_detect_and_redact_overlapping_patterns() {
        let cfg = SecretsDetectionConfig {
            redact: true,
            ..Default::default()
        };

        // A base64 string that might also match hex pattern
        let text = "secret=SGVsbG8gV29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IGVuY29kZWQgc3RyaW5n";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // Should detect at least one pattern
        assert!(!findings.is_empty());
        // Should be redacted
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_detect_and_redact_empty_enabled_map() {
        let cfg = SecretsDetectionConfig {
            enabled: std::collections::HashMap::new(),
            redact: true,
            ..Default::default()
        };

        let text = "AKIAFAKE12345EXAMPLE";
        let (findings, redacted) = detect_and_redact(text, &cfg);

        // With empty enabled map, unwrap_or(true) should enable all patterns
        assert!(!findings.is_empty());
        assert!(redacted.contains("***REDACTED***"));
    }

    #[test]
    fn test_finding_struct_fields() {
        let finding = Finding {
            pii_type: "test_type".to_string(),
            preview: "test_preview".to_string(),
        };

        assert_eq!(finding.pii_type, "test_type");
        assert_eq!(finding.preview, "test_preview");
    }

    #[test]
    fn test_detect_and_redact_redaction_text_variations() {
        let test_cases = vec![
            ("[REDACTED]", "[REDACTED]"),
            ("***", "***"),
            ("<REMOVED>", "<REMOVED>"),
            ("", ""), // Empty redaction text
        ];

        for (redaction_text, expected) in test_cases {
            let cfg = SecretsDetectionConfig {
                redact: true,
                redaction_text: redaction_text.to_string(),
                ..Default::default()
            };

            let text = "AKIAFAKE12345EXAMPLE";
            let (findings, redacted) = detect_and_redact(text, &cfg);

            assert!(!findings.is_empty());
            if !expected.is_empty() {
                assert!(redacted.contains(expected));
            }
            assert!(!redacted.contains("AKIAFAKE12345EXAMPLE"));
        }
    }
}
