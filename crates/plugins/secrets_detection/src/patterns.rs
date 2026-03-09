use regex::Regex;
use std::collections::HashMap;
use std::sync::LazyLock;

/// Regex patterns for complex secret detection
pub static PATTERNS: LazyLock<HashMap<&'static str, Regex>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert(
        "aws_access_key_id",
        Regex::new(r"\bAKIA[0-9A-Z]{16}\b")
            .expect("Failed to compile AWS Access Key ID regex pattern"),
    );
    m.insert(
        "aws_secret_access_key",
        Regex::new(r"(?i)aws.{0,20}(?:secret|access).{0,20}=\s*([A-Za-z0-9/+=]{40})")
            .expect("Failed to compile AWS Secret Access Key regex pattern"),
    );
    m.insert(
        "google_api_key",
        Regex::new(r"\bAIza[0-9A-Za-z\-_]{35}\b")
            .expect("Failed to compile Google API Key regex pattern"),
    );
    m.insert(
        "slack_token",
        Regex::new(r"\bxox[abpqr]-[0-9A-Za-z\-]{10,48}\b")
            .expect("Failed to compile Slack Token regex pattern"),
    );
    m.insert(
        "private_key_block",
        Regex::new(r"-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----")
            .expect("Failed to compile Private Key Block regex pattern"),
    );
    m.insert(
        "jwt_like",
        Regex::new(r"\beyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\b")
            .expect("Failed to compile JWT-like regex pattern"),
    );
    m.insert(
        "hex_secret_32",
        Regex::new(r"(?i)\b[a-f0-9]{32,}\b").expect("Failed to compile Hex Secret regex pattern"),
    );
    m.insert(
        "base64_24",
        Regex::new(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
            .expect("Failed to compile Base64 regex pattern"),
    );
    m
});

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_patterns_initialization() {
        // Verify all expected patterns are present
        assert!(PATTERNS.contains_key("aws_access_key_id"));
        assert!(PATTERNS.contains_key("aws_secret_access_key"));
        assert!(PATTERNS.contains_key("google_api_key"));
        assert!(PATTERNS.contains_key("slack_token"));
        assert!(PATTERNS.contains_key("private_key_block"));
        assert!(PATTERNS.contains_key("jwt_like"));
        assert!(PATTERNS.contains_key("hex_secret_32"));
        assert!(PATTERNS.contains_key("base64_24"));
        assert_eq!(PATTERNS.len(), 8);
    }

    #[test]
    fn test_aws_access_key_id_pattern() {
        let pattern = PATTERNS.get("aws_access_key_id").unwrap();

        // Valid AWS access key IDs
        assert!(
            pattern.is_match("AKIAFAKE12345EXAMPLE"),
            "Should match valid AWS access key ID"
        );
        assert!(
            pattern.is_match("AKIAFAKE67890EXAMPLE"),
            "Should match valid AWS access key ID"
        );

        // Invalid patterns
        assert!(!pattern.is_match("AKIA123"), "Should not match: too short");
        assert!(
            !pattern.is_match("BKIAFAKE12345EXAMPLE"),
            "Should not match: wrong prefix"
        );
        assert!(
            !pattern.is_match("akiafake12345example"),
            "Should not match: lowercase"
        );
    }

    #[test]
    fn test_aws_secret_access_key_pattern() {
        let pattern = PATTERNS.get("aws_secret_access_key").unwrap();

        // Valid AWS secret patterns
        assert!(
            pattern.is_match("aws_secret_access_key = FAKESecretAccessKeyForTestingEXAMPLE0000"),
            "Should match valid AWS secret access key"
        );
        assert!(
            pattern.is_match("AWS_SECRET=FAKESecretAccessKeyForTestingEXAMPLE0000"),
            "Should match valid AWS secret"
        );
        assert!(
            pattern.is_match("aws access key=FAKESecretAccessKeyForTestingEXAMPLE0000"),
            "Should match valid AWS access key"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("aws_secret = short"),
            "Should not match: too short"
        );
    }

    #[test]
    fn test_google_api_key_pattern() {
        let pattern = PATTERNS.get("google_api_key").unwrap();

        // Valid Google API keys (AIza + exactly 35 chars)
        assert!(
            pattern.is_match("AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"),
            "Should match valid Google API key"
        );
        assert!(
            pattern.is_match("AIzaFAKE_KEY_FOR_TESTING_ONLY_fake56789"),
            "Should match valid Google API key"
        );

        // Invalid patterns
        assert!(!pattern.is_match("AIza123"), "Should not match: too short");
        assert!(
            !pattern.is_match("BIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"),
            "Should not match: wrong prefix"
        );
    }

    #[test]
    fn test_slack_token_pattern() {
        let pattern = PATTERNS.get("slack_token").unwrap();

        // Valid Slack tokens (using xoxr- prefix to avoid push protection false positives)
        assert!(
            pattern.is_match("xoxr-fake-000000000-fake000000000-fakefakefakefake"),
            "Should match valid Slack refresh token"
        );
        assert!(
            pattern.is_match("xoxq-fake000000"),
            "Should match valid Slack token"
        );
        assert!(
            pattern.is_match("xoxr-fake-000000000-fake000000000-fakefakefakefake"),
            "Should match valid Slack token"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("xoxz-123"),
            "Should not match: wrong token type"
        );
        assert!(
            !pattern.is_match("yoxr-fake000000"),
            "Should not match: wrong prefix"
        );
    }

    #[test]
    fn test_private_key_block_pattern() {
        let pattern = PATTERNS.get("private_key_block").unwrap();

        // Valid private key headers
        assert!(
            pattern.is_match("-----BEGIN RSA PRIVATE KEY-----"),
            "Should match RSA private key header"
        );
        assert!(
            pattern.is_match("-----BEGIN DSA PRIVATE KEY-----"),
            "Should match DSA private key header"
        );
        assert!(
            pattern.is_match("-----BEGIN EC PRIVATE KEY-----"),
            "Should match EC private key header"
        );
        assert!(
            pattern.is_match("-----BEGIN OPENSSH PRIVATE KEY-----"),
            "Should match OpenSSH private key header"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("-----BEGIN PUBLIC KEY-----"),
            "Should not match: public key"
        );
        assert!(
            !pattern.is_match("-----BEGIN CERTIFICATE-----"),
            "Should not match: certificate"
        );
    }

    #[test]
    fn test_jwt_like_pattern() {
        let pattern = PATTERNS.get("jwt_like").unwrap();

        // Valid JWT-like tokens
        assert!(
            pattern.is_match("eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678"),
            "Should match valid JWT token"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("eyJ.eyJ.abc"),
            "Should not match: too short"
        );
        assert!(
            !pattern.is_match("abc.def.ghi"),
            "Should not match: wrong prefix"
        );
    }

    #[test]
    fn test_hex_secret_32_pattern() {
        let pattern = PATTERNS.get("hex_secret_32").unwrap();

        // Valid hex secrets (32+ chars)
        assert!(
            pattern.is_match("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"),
            "Should match valid 32-char hex secret"
        );
        assert!(
            pattern.is_match("ABCDEF1234567890ABCDEF1234567890"),
            "Should match valid uppercase hex secret"
        );
        assert!(
            pattern.is_match("0123456789abcdef0123456789abcdef"),
            "Should match valid hex secret"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5"),
            "Should not match: too short (31 chars)"
        );
        assert!(
            !pattern.is_match("g1h2i3j4k5l6m7n8o9p0q1r2s3t4u5v6"),
            "Should not match: invalid hex chars"
        );
    }

    #[test]
    fn test_base64_24_pattern() {
        let pattern = PATTERNS.get("base64_24").unwrap();

        // Valid base64 strings (24+ chars)
        assert!(
            pattern.is_match("dGhpcyBpcyBhIHRlc3Qgc3RyaW5n"),
            "Should match valid base64 string"
        );
        assert!(
            pattern.is_match("YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo="),
            "Should match valid base64 string with padding"
        );
        assert!(
            pattern.is_match("MTIzNDU2Nzg5MDEyMzQ1Njc4OTA=="),
            "Should match valid base64 string with double padding"
        );

        // Invalid patterns
        assert!(
            !pattern.is_match("dGhpcyBpcyBhIHRlc3Q"),
            "Should not match: too short (< 24 chars)"
        );
    }

    #[test]
    fn test_pattern_matching_real_world_aws() {
        let aws_key_pattern = PATTERNS.get("aws_access_key_id").unwrap();
        let aws_secret_pattern = PATTERNS.get("aws_secret_access_key").unwrap();

        let text = r#"
            AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE
            AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000
        "#;

        assert!(
            aws_key_pattern.is_match(text),
            "Should detect AWS access key in real-world text"
        );
        assert!(
            aws_secret_pattern.is_match(text),
            "Should detect AWS secret key in real-world text"
        );
    }

    #[test]
    fn test_pattern_matching_real_world_mixed() {
        let jwt_pattern = PATTERNS.get("jwt_like").unwrap();
        let hex_pattern = PATTERNS.get("hex_secret_32").unwrap();

        let text = r#"
            Authorization: Bearer eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678
            API_SECRET=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
        "#;

        assert!(
            jwt_pattern.is_match(text),
            "Should detect JWT token in real-world text"
        );
        assert!(
            hex_pattern.is_match(text),
            "Should detect hex secret in real-world text"
        );
    }
}
