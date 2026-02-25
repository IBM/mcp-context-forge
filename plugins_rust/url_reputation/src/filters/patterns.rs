use std::collections::HashSet;
use regex::Regex;


pub fn in_blocked_patterns_regex(domain: &str, blocked_patterns: &[Regex]) -> bool {
    blocked_patterns.iter().any(|re| re.is_match(domain))
}

pub fn in_allow_patterns_regex(domain: &str, allowed_pattens: &[Regex]) -> bool {
    allowed_pattens.iter().any(|re| re.is_match(domain))
}

pub fn in_domain_list(domain: &str, check_domains: &HashSet<String>) -> bool {
    if check_domains.contains(domain) {
        return true;
    }

    let parts: Vec<&str> = domain.split('.').collect();
    for i in 0..parts.len() {
        let candidate = parts[i..].join(".");
        if check_domains.contains(&candidate) {
            return true;
        }
    }

    false
}
