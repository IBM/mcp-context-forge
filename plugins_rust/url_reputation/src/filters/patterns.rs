use regex::Regex;

pub fn in_blocked_patterns_regex(domain: &str, blocked_patterns: &[Regex]) -> bool {
    blocked_patterns.iter().any(|re| re.is_match(domain))
}


pub fn in_allow_patterns_regex(domain: &str, allowed_pattens: &[Regex]) -> bool {
    allowed_pattens.iter().any(|re| re.is_match(domain))
}
