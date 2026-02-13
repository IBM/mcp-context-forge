

pub fn in_blocked_list(domain: &str, blocked_domains: &[&str]) -> bool {
    blocked_domains.contains(&domain)
}

pub fn in_blocked_patterns(domain: &str, blocked_patterns: &[&str]) -> bool {
    for pattern in blocked_patterns {
        if domain.contains(pattern) {
            return true;
        }
    }
    false
}


