use crate::{
    filters::{heuristic, patterns},
    types::{PluginViolation, URLPluginResult, URLReputationConfig},
};
use anyhow;
use pyo3::prelude::*;
use regex::Regex;
use std::{
    collections::HashMap,
    net::{Ipv4Addr, Ipv6Addr},
};
use url::Url;

/// Evaluates a URL against the URL reputation configuration.
///
/// This function:
/// 1. Parses and normalizes the URL (trim + lowercase).
/// 2. Extracts the domain.
/// 4. Check if the domain is an ipv4 or ipv6
/// 4. Applies reputation checks in the following order:
///    - Whitelist domain
///    - Blocked domains
///    - Blocked URL patterns
///    - heuristic check if not an ip address
///         - Entropy-based heuristic on the domain
///         - Valid TLD in IANNA list
///         - Domain unicode security check
///
/// If any blocking rule matches, a `URLPluginResult` is returned with
/// `continue_processing = false` and a populated `PluginViolation`.
///
/// If no rule matches, processing is allowed.
///
/// # Arguments
/// * `url` - The URL to evaluate.
/// * `config` - `URLReputationConfig`
///                 whitelist_domains: set
///                 blocked_domains: set
///                 blocked_patterns: set
///                 use_heuristic_check: bool
///                 entropy_threshold: float
///                 block_non_secure_http: bool
///
/// # Returns
/// * `Ok(URLPluginResult)` indicating whether processing should continue
///   and optional violation details.
///
/// # Notes
///     - Whitelisted domains take precedence over all blocking rules.
///     - The domain is normalized to lowercase before evaluation.
///     - Emptty domains/url are considered invalid.

// pub struct URLReputationConfig {
//     pub whitelist_domains: HashSet<String>,
//     pub allowed_patterns: Vec<String>,
//     pub blocked_domains: HashSet<String>,
//     pub blocked_patterns: HashSet<String>,
//     pub use_heuristic_check: bool,
//     pub entropy_threshold: f32,
//     pub block_non_secure_http: bool,
// }

#[pyclass]
pub struct URLReputationPlugin {
    config: URLReputationConfig,
    allowed_patterns: Vec<Regex>, // store compiled regex
    blocked_patterns: Vec<Regex>,
}

#[pymethods]
impl URLReputationPlugin {
    #[new]
    fn new(config: URLReputationConfig) -> Self {
        let allowed_patterns = config
            .allowed_patterns
            .iter()
            .filter_map(|p| Regex::new(p).ok())
            .collect();
        let blocked_patterns = config
            .blocked_patterns
            .iter()
            .filter_map(|p| Regex::new(p).ok())
            .collect();
        Self {
            config,
            allowed_patterns,
            blocked_patterns,
        }
    }

    fn validate_url(&self, url: &str) -> anyhow::Result<URLPluginResult> {
        let parsed_url = match Url::parse(&url.trim().to_lowercase()) {
            Ok(url) => url,
            Err(_) => {
                return Ok(URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Could not parse url".to_string(),
                        description: format!("URL {} is blocked", url),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                    }),
                });
            }
        };
        let domain = match parsed_url.host_str() {
            Some(domain) => domain,
            None => {
                return Ok(URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Could not parse domain".to_string(),
                        description: format!("URL {} is blocked", url),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                    }),
                });
            }
        };

        let ip_domain = domain.parse::<Ipv4Addr>().is_ok()
            || domain
                .trim_start_matches('[')
                .trim_end_matches(']')
                .parse::<Ipv6Addr>()
                .is_ok();

        let scheme = parsed_url.scheme();

        // check whitelisted domains
        if self.config.whitelist_domains.contains(domain) {
            return Ok(URLPluginResult {
                continue_processing: true,
                violation: None,
            });
        }

        if patterns::in_allow_patterns_regex(url, &self.allowed_patterns) {
            return Ok(URLPluginResult {
                continue_processing: true,
                violation: None,
            });
        }
        // check non secure http
        if self.config.block_non_secure_http && scheme != "https" {
            return Ok(URLPluginResult {
                continue_processing: false,
                violation: Some(PluginViolation {
                    reason: "Blocked non secure http url".to_string(),
                    description: format!("URL {} is blocked", url),
                    code: "URL_REPUTATION_BLOCK".to_string(),
                    details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                }),
            });
        }
        // check for patterns in the url
        if patterns::in_blocked_patterns_regex(url, &self.blocked_patterns) {
            return Ok(URLPluginResult {
                continue_processing: false,
                violation: Some(PluginViolation {
                    reason: "Blocked pattern".to_string(),
                    description: format!("URL matches blocked pattern"),
                    code: "URL_REPUTATION_BLOCK".to_string(),
                    details: Some(HashMap::from([("domain".to_string(), url.to_string())])),
                }),
            });
        }
        // skip heuristic checks if the domain is an IP address
        if !ip_domain && self.config.use_heuristic_check {
            if !heuristic::passed_entropy(domain, self.config.entropy_threshold) {
                return Ok(URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "High entropy domain".to_string(),
                        description: format!("Domain exceeds entropy threshold: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), url.to_string())])),
                    }),
                });
            }
            // check for valid tld
            if !heuristic::is_tld_legal(domain) {
                return Ok(URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Illegal TLD".to_string(),
                        description: format!("Domain TLD not legal: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), url.to_string())])),
                    }),
                });
            }
            // check for unicode security
            if !heuristic::is_domain_unicode_secure(domain) {
                return Ok(URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Domain unicode is not secure".to_string(),
                        description: format!("Domain unicode is not secure for domain: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), url.to_string())])),
                    }),
                });
            }
        }
        Ok(URLPluginResult {
            continue_processing: true,
            violation: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn test_whitelisted_domain() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::from(["example.com".to_string()]),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://example.com";

        let result = plugin.validate_url(url).unwrap();
        assert!(true == result.continue_processing);
    }

    #[test]
    fn test_non_secure_http() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "http://ibm.com";

        let result = plugin.validate_url(url).unwrap();
        assert!(!result.continue_processing);
        assert_eq!(
            result.violation.unwrap().reason,
            "Blocked non secure http url"
        );
    }

    #[test]
    fn test_allowed_pattern() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: vec!["0932".to_string(), "safe\\.com/allowed".to_string()],
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://safe.com/allowed";

        let result = plugin.validate_url(url).unwrap();
        assert!(result.continue_processing);
    }

    #[test]
    fn test_blocked_pattern() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec!["crypto.*".to_string()],
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://safe.com/crypto-invest";

        let result = plugin.validate_url(url).unwrap();
        assert!(!result.continue_processing);
        assert_eq!(result.violation.unwrap().reason, "Blocked pattern");
    }

    #[test]
    fn test_valid_url() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec!["crypto.*".to_string()],
            use_heuristic_check: false,
            entropy_threshold: 3.65,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://rust-lang.org";

        let result = plugin.validate_url(url).unwrap();
        assert!(result.continue_processing);
    }

    #[test]
    fn test_could_not_parse_url_invalid_character() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec!["crypto.*".to_string()],
            use_heuristic_check: false,
            entropy_threshold: 3.65,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "ht!tp://example.com"; // Zero-width joiner U+200D
        let result = plugin.validate_url(url).unwrap();
        assert!(false == result.continue_processing);
        assert!(result.violation.unwrap().reason == "Could not parse url".to_string())
    }

    #[test]
    fn test_could_not_parse_domain_invalid_character() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec![],
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "mailto:user@example.com"; // Zero-width joiner U+200D
        let result = plugin.validate_url(url).unwrap();
        assert!(false == result.continue_processing);
        assert!(result.violation.unwrap().reason == "Could not parse domain".to_string())
    }

    #[test]
    fn test_heuristic_high_entropy_domain() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec![],
            use_heuristic_check: true,
            entropy_threshold: 3.65,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://axb12c34d56ef.com";
        let result = plugin.validate_url(url).unwrap();
        assert!(false == result.continue_processing);
        assert!(result.violation.unwrap().reason == "High entropy domain");
    }

    #[test]
    fn test_heuristic_invalid_tld() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec![],
            use_heuristic_check: true,
            entropy_threshold: 5.65,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://test.daks/test";

        let result = plugin.validate_url(url).unwrap();
        assert!(false == result.continue_processing);
        assert!(result.violation.unwrap().reason == "Illegal TLD");
    }

    #[test]
    fn test_heuristic_domain_too_long() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let domain_label = "long_domain".repeat(30);
        let url = format!("https://{}.com", domain_label);
        let result = plugin.validate_url(&url).unwrap();

        assert!(!result.continue_processing);
        assert_eq!(
            result.violation.unwrap().reason,
            "Domain unicode is not secure"
        );
    }

    #[test]
    fn test_is_domain_unicode_secure_mixed_scripts() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://pаypal.com/test"; // Cyrillic 'а'
        let result = plugin.validate_url(url).unwrap();

        assert!(!result.continue_processing);
        assert_eq!(
            result.violation.unwrap().reason,
            "Domain unicode is not secure"
        );
    }

    #[test]
    fn test_is_domain_unicode_secure_pure_ascii() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://domain.com";
        let result = plugin.validate_url(url).unwrap();

        assert!(result.continue_processing);
    }

    #[test]
    fn test_is_domain_unicode_secure_empty_label() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://my..com";
        let result = plugin.validate_url(url).unwrap();

        assert!(!result.continue_processing);
        assert_eq!(
            result.violation.unwrap().reason,
            "Domain unicode is not secure"
        );
    }

    #[test]
    fn test_is_domain_unicode_invalid_characters() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://exa!mple.com";
        let result = plugin.validate_url(url).unwrap();

        assert!(!result.continue_processing);
        assert_eq!(
            result.violation.unwrap().reason,
            "Domain unicode is not secure"
        );
    }

    #[test]
    fn test_url_valid_ipv4() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://192.168.0.1:442";
        let result = plugin.validate_url(url).unwrap();

        assert!(result.continue_processing);
    }

    #[test]
    fn test_url_invalid_ipv4() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://332.168.0.1:442";
        let result = plugin.validate_url(url).unwrap();

        assert!(!result.continue_processing);
    }

    #[test]
    fn test_url_valid_ipv6() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://[2001:0db8:020c:0001:0000:0000:0000:0bbb]:442/";
        let result = plugin.validate_url(url).unwrap();

        assert!(result.continue_processing);
    }

    #[test]
    fn test_url_invalid_ipv6() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: true,
            entropy_threshold: 5.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);

        let url = "https://[2001:db8::85a3::8a2e:370:7334 ]:442/";
        let result = plugin.validate_url(url).unwrap();

        assert!(!result.continue_processing);
    }
}
