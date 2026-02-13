// Computes the Shannon entropy of a string to measure randomness of the domain.

fn shannon_entropy(domain: &str, domain_len: usize) -> f32 {
    // Calculate Shannon entropy of a string.
    //
    // input:
    //   domain: the string to calculate entropy for.
    //   domain_len: the length of the string.
    // output:
    //    the Shannon entropy of the string.

    let mut frequency = [0usize; 256];
    let mut entropy = 0.0;
    for &b in domain.as_bytes() {
        frequency[b] += 1;
    }

    for count in frequency.iter() {
        if count > &0 {
            let p = (*count as f32) / (domain_len as f32);
            entropy += -p * p.log2()
        }
    }
    entropy
}

pub fn check_entropy(domain: &str, entropy_treshold: f32) -> bool {
    let domain_len = domain.len();
    // do not check entropy for small domains
    if domain_len < 8 {
        return true;
    }
    return shannon_entropy(&domain, domain_len) > entropy_treshold;
}
