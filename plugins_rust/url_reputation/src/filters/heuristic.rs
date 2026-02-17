// The heuristic module try to detect Domain Generation Algorithms (DGS)
// Computes the Shannon entropy of a string to measure randomness of the domain.
use super::iana_tlds::VALID_TLD_SET;
use idna::domain_to_unicode;
use unicode_security::{GeneralSecurityProfile, RestrictionLevel, RestrictionLevelDetection};

fn shannon_entropy(domain: &str, domain_len: usize) -> f32 {
    // Calculate Shannon entropy of a string.
    //
    // input:
    //   domain: the string to calculate entropy for.
    //   domain_len: the length of the string.
    // output:
    //    the Shannon entropy of the string.
    if domain.is_empty() {
        return 0.0;
    }
    let mut frequency = [0usize; 256];
    let mut entropy = 0.0;
    for &b in domain.as_bytes() {
        frequency[b as usize] += 1;
    }

    for count in frequency.iter() {
        if count > &0 {
            let p = (*count as f32) / (domain_len as f32);
            entropy += -p * p.log2()
        }
    }
    entropy
}

pub fn passed_entropy(domain: &str, entropy_threshold: f32) -> bool {
    let domain_len = domain.len();
    // do not check entropy for small domains
    if domain_len < 8 {
        return true;
    }
    shannon_entropy(domain, domain_len) <= entropy_threshold
}

pub fn is_tld_legal(domain: &str) -> bool {
    // Check for IANA database for valid tld
    let tld = domain
        .trim()
        .rsplit('.')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    VALID_TLD_SET.contains(&tld)
}

pub fn is_domain_unicode_secure(domain: &str) -> bool {
    let (unicode, errors) = domain_to_unicode(domain);
    println!("Error {:?}", errors);
    if errors.is_err() || unicode.len() > 253 {
        return false;
    }

    for label in unicode.split('.') {
        if label.is_empty() {
            return false;
        }

        // Strip hyphens
        let cleaned: String = label.chars().filter(|c| *c != '-').collect();
        if cleaned.is_empty() {
            return false;
        }

        // Reject invisible or invalid identifier characters
        if !cleaned
            .chars()
            .all(GeneralSecurityProfile::identifier_allowed)
        {
            return false;
        } else {
            println!("DOMAIN {}", cleaned);
        }
        // Restriction level check
        let level = cleaned.detect_restriction_level();
        match level {
            RestrictionLevel::ASCIIOnly
            | RestrictionLevel::SingleScript
            | RestrictionLevel::HighlyRestrictive => {}
            RestrictionLevel::ModeratelyRestrictive
            | RestrictionLevel::MinimallyRestrictive
            | RestrictionLevel::Unrestricted => {
                return false;
            }
        }
    }

    true
}
