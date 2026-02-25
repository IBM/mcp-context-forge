use crate::{
    filters::{
        heuristic,
        patterns::{self, in_domain_list},
    },
    types::{PluginViolation, URLPluginResult, URLReputationConfig},
};
use log::warn;
use pyo3::{prelude::*, types::PyDict};
use regex::Regex;
use std::{
    collections::HashMap,
    net::{Ipv4Addr, Ipv6Addr},
};
use url::Url;

#[pyclass]
pub struct URLReputationPlugin {
    config: URLReputationConfig,
    allowed_patterns: Vec<Regex>, // store compiled regex
    blocked_patterns: Vec<Regex>,
}

#[pymethods]
impl URLReputationPlugin {
    #[new]
    pub fn new(config: URLReputationConfig) -> Self {
        // Normalize domains to lowercase for case-insensitive matching
        let config = config.normalize_domains();
        
        let allowed_patterns = config
            .allowed_patterns
            .iter()
            .filter_map(|p| match Regex::new(p) {
                Ok(regex) => Some(regex),
                Err(e) => {
                    warn!("Failed to compile allowed pattern '{}': {}", p, e);
                    None
                }
            })
            .collect();
        let blocked_patterns = config
            .blocked_patterns
            .iter()
            .filter_map(|p| match Regex::new(p) {
                Ok(regex) => Some(regex),
                Err(e) => {
                    warn!("Failed to compile blocked pattern '{}': {}", p, e);
                    None
                }
            })
            .collect();

        Self {
            config,
            allowed_patterns,
            blocked_patterns,
        }
    }
    // exposed function return python dict
    fn validate_url_py(&self, py: Python, url: &str) -> PyResult<Py<PyDict>> {
        let result = self.validate_url(url);
        result.to_py_dict(py)
    }

    pub fn validate_url(&self, url: &str) -> URLPluginResult {
        let parsed_url = match Url::parse(&url.trim().to_lowercase()) {
            Ok(url) => url,
            Err(_) => {
                return URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Could not parse url".to_string(),
                        description: format!("URL {} is blocked", url),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                    }),
                };
            }
        };
        let domain = match parsed_url.host_str() {
            Some(domain) => domain,
            None => {
                return URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Could not parse domain".to_string(),
                        description: format!("URL {} is blocked", url),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                    }),
                };
            }
        };

        let ip_domain = domain.parse::<Ipv4Addr>().is_ok()
            || domain
                .trim_start_matches('[')
                .trim_end_matches(']')
                .parse::<Ipv6Addr>()
                .is_ok();

        let scheme = parsed_url.scheme();

        // check whitelist
        if in_domain_list(domain, &self.config.whitelist_domains) {
            return URLPluginResult {
                continue_processing: true,
                violation: None,
            };
        }
        // check for allowed patterns
        if patterns::in_allow_patterns_regex(url, &self.allowed_patterns) {
            return URLPluginResult {
                continue_processing: true,
                violation: None,
            };
        }
        // check non secure http
        if self.config.block_non_secure_http && scheme != "https" {
            return URLPluginResult {
                continue_processing: false,
                violation: Some(PluginViolation {
                    reason: "Blocked non secure http url".to_string(),
                    description: format!("URL {} is blocked", url),
                    code: "URL_REPUTATION_BLOCK".to_string(),
                    details: Some(HashMap::from([("url".to_string(), url.to_string())])),
                }),
            };
        }
        // check blocked domains
        if in_domain_list(domain, &self.config.blocked_domains) {
            return URLPluginResult {
                continue_processing: false,
                violation: Some(PluginViolation {
                    reason: "Domain in blocked set".to_string(),
                    description: format!("Domain '{}' in blocked set", domain),
                    code: "URL_REPUTATION_BLOCK".to_string(),
                    details: Some(HashMap::from([("domain".to_string(), domain.to_string())])),
                }),
            };
        }
        // check for blocked patterns in the url
        if patterns::in_blocked_patterns_regex(url, &self.blocked_patterns) {
            return URLPluginResult {
                continue_processing: false,
                violation: Some(PluginViolation {
                    reason: "Blocked pattern".to_string(),
                    description: "URL matches blocked pattern".to_string(),
                    code: "URL_REPUTATION_BLOCK".to_string(),
                    details: Some(HashMap::from([("domain".to_string(), domain.to_string())])),
                }),
            };
        }
        // skip heuristic checks if the domain is an IP address
        if !ip_domain && self.config.use_heuristic_check {
            if !heuristic::passed_entropy(domain, self.config.entropy_threshold) {
                return URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "High entropy domain".to_string(),
                        description: format!("Domain exceeds entropy threshold: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), domain.to_string())])),
                    }),
                };
            }
            // check for valid tld
            if !heuristic::is_tld_legal(domain) {
                return URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Illegal TLD".to_string(),
                        description: format!("Domain TLD not legal: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), domain.to_string())])),
                    }),
                };
            }
            // check for unicode security
            if !heuristic::is_domain_unicode_secure(domain) {
                return URLPluginResult {
                    continue_processing: false,
                    violation: Some(PluginViolation {
                        reason: "Domain unicode is not secure".to_string(),
                        description: format!("Domain unicode is not secure for domain: {}", domain),
                        code: "URL_REPUTATION_BLOCK".to_string(),
                        details: Some(HashMap::from([("domain".to_string(), domain.to_string())])),
                    }),
                };
            }
        }
        URLPluginResult {
            continue_processing: true,
            violation: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::*;

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

        let result = plugin.validate_url(url);
        assert!(result.continue_processing);
    }

    #[test]
    fn test_blocked_domain() {
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::from(["bad.example".to_string()]),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: true,
        };
        let plugin = URLReputationPlugin::new(config);
        let url = "https://api.bad.example/v1";

        let result = plugin.validate_url(url);
        assert!(!result.continue_processing);
        assert_eq!(result.violation.unwrap().reason, "Domain in blocked set");
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

        let result = plugin.validate_url(url);
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

        let result = plugin.validate_url(url);
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

        let result = plugin.validate_url(url);
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

        let result = plugin.validate_url(url);
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
        let result = plugin.validate_url(url);
        assert!(!result.continue_processing);
        assert!(result.violation.unwrap().reason == "Could not parse url")
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
        let result = plugin.validate_url(url);
        assert!(!result.continue_processing);
        assert!(result.violation.unwrap().reason == "Could not parse domain")
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
        let result = plugin.validate_url(url);
        assert!(!result.continue_processing);
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

        let result = plugin.validate_url(url);
        assert!(!result.continue_processing);
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
        let result = plugin.validate_url(&url);

        assert!(result.continue_processing == false);
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
        let result = plugin.validate_url(url);

        assert!(result.continue_processing == false);
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
        let result = plugin.validate_url(url);

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
        let result = plugin.validate_url(url);

        assert!(result.continue_processing == false);
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
        let result = plugin.validate_url(url);

        assert!(result.continue_processing == false);
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
        let result = plugin.validate_url(url);

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
        let result = plugin.validate_url(url);

        assert!(result.continue_processing == false);
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
        let result = plugin.validate_url(url);

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
        let result = plugin.validate_url(url);

        assert!(result.continue_processing == false);
    }

    #[test]
    fn test_invalid_allowed_regex_pattern() {
        // Test that invalid regex patterns in allowed_patterns are logged and skipped
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: vec![
                "valid\\.pattern".to_string(),
                "[invalid(regex".to_string(),  // Invalid regex
                "another\\.valid".to_string(),
            ],
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: false,
        };
        let plugin = URLReputationPlugin::new(config);
        
        // Should have compiled 2 valid patterns, skipped 1 invalid
        assert_eq!(plugin.allowed_patterns.len(), 2);
        
        // Valid pattern should still work
        let result = plugin.validate_url("https://example.com/valid.pattern");
        assert!(result.continue_processing);
    }

    #[test]
    fn test_invalid_blocked_regex_pattern() {
        // Test that invalid regex patterns in blocked_patterns are logged and skipped
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: vec![
                "valid.*pattern".to_string(),
                "*invalid[regex".to_string(),  // Invalid regex
                "another.*blocked".to_string(),
            ],
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: false,
        };
        let plugin = URLReputationPlugin::new(config);
        
        // Should have compiled 2 valid patterns, skipped 1 invalid
        assert_eq!(plugin.blocked_patterns.len(), 2);
        
        // Valid pattern should still work
        let result = plugin.validate_url("https://example.com/valid-pattern-test");
        assert!(!result.continue_processing);
        assert_eq!(result.violation.unwrap().reason, "Blocked pattern");
    }

    #[test]
    fn test_case_insensitive_whitelist() {
        // Test that domain normalization works for whitelist
        let config = URLReputationConfig {
            whitelist_domains: HashSet::from(["Example.COM".to_string()]),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::new(),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: false,
        };
        let plugin = URLReputationPlugin::new(config);
        
        // Lowercase URL should match uppercase whitelist entry
        let result = plugin.validate_url("https://example.com/path");
        assert!(result.continue_processing);
        
        // Mixed case should also work
        let result = plugin.validate_url("https://EXAMPLE.com/path");
        assert!(result.continue_processing);
    }

    #[test]
    fn test_case_insensitive_blocked() {
        // Test that domain normalization works for blocked domains
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::from(["BAD.Example".to_string()]),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: false,
        };
        let plugin = URLReputationPlugin::new(config);
        
        // Lowercase URL should match mixed-case blocked entry
        let result = plugin.validate_url("https://bad.example/path");
        assert!(!result.continue_processing);
        assert_eq!(result.violation.unwrap().reason, "Domain in blocked set");
    }

    #[test]
    fn test_subdomain_matching() {
        // Test that subdomains are properly matched
        let config = URLReputationConfig {
            whitelist_domains: HashSet::new(),
            allowed_patterns: Vec::new(),
            blocked_domains: HashSet::from(["blocked.com".to_string()]),
            blocked_patterns: Vec::new(),
            use_heuristic_check: false,
            entropy_threshold: 0.0,
            block_non_secure_http: false,
        };
        let plugin = URLReputationPlugin::new(config);
        
        // Subdomain should be blocked
        let result = plugin.validate_url("https://api.blocked.com/v1");
        assert!(!result.continue_processing);
        
        // Deep subdomain should also be blocked
        let result = plugin.validate_url("https://deep.api.blocked.com/v1");
        assert!(!result.continue_processing);
    }
}
