use crate::patterns::PATTERNS;
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct SecretsDetectionConfig {
    pub enabled: HashMap<String, bool>,
    pub redact: bool,
    pub redaction_text: String,
    pub block_on_detection: bool,
    pub min_findings_to_block: u32,
}

impl Default for SecretsDetectionConfig {
    fn default() -> Self {
        let mut enabled: HashMap<String, bool> =
            PATTERNS.keys().map(|&k| (k.to_string(), true)).collect();
        enabled.insert("generic_api_key_assignment".to_string(), false);

        Self {
            enabled,
            redact: false,
            redaction_text: "***REDACTED***".to_string(),
            block_on_detection: true,
            min_findings_to_block: 1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_secrets_detection_config_default() {
        let config = SecretsDetectionConfig::default();

        // Verify default values
        assert!(!config.redact);
        assert_eq!(config.redaction_text, "***REDACTED***");
        assert!(config.block_on_detection);
        assert_eq!(config.min_findings_to_block, 1);

        assert_eq!(
            config.enabled.len(),
            11,
            "Should have 11 patterns configured"
        );
        assert_eq!(
            config.enabled.get("generic_api_key_assignment"),
            Some(&false),
            "Broad generic API-key detection should be opt-in"
        );
        for (pattern_name, enabled) in config.enabled.iter() {
            if pattern_name == "generic_api_key_assignment" {
                continue;
            }
            assert!(
                enabled,
                "Pattern '{}' should be enabled by default",
                pattern_name
            );
        }
    }

    #[test]
    fn test_secrets_detection_config_custom() {
        let mut enabled = HashMap::new();
        enabled.insert("aws_access_key_id".to_string(), true);
        enabled.insert("google_api_key".to_string(), false);

        let config = SecretsDetectionConfig {
            enabled,
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            block_on_detection: false,
            min_findings_to_block: 3,
        };

        assert!(config.redact);
        assert_eq!(config.redaction_text, "[REDACTED]");
        assert!(!config.block_on_detection);
        assert_eq!(config.min_findings_to_block, 3);
        assert_eq!(config.enabled.get("aws_access_key_id"), Some(&true));
        assert_eq!(config.enabled.get("google_api_key"), Some(&false));
    }

    #[test]
    fn test_config_clone() {
        let config1 = SecretsDetectionConfig::default();
        let config2 = config1.clone();

        assert_eq!(config1.redact, config2.redact);
        assert_eq!(config1.redaction_text, config2.redaction_text);
        assert_eq!(config1.block_on_detection, config2.block_on_detection);
        assert_eq!(config1.min_findings_to_block, config2.min_findings_to_block);
    }
}
