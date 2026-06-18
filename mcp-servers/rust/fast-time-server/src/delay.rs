// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use rand_distr::Distribution;
use rand_distr::Normal;

use crate::config::MAX_DELAY_MS;

/// Compute the actual delay in ms, optionally sampling from a normal distribution.
/// Returns the mean unchanged when stddev is None, zero, or negative.
pub(crate) fn compute_delay(mean_ms: u64, stddev: Option<f64>) -> u64 {
    match stddev {
        Some(sd) if sd > 0.0 => {
            let dist = Normal::new(mean_ms as f64, sd)
                .unwrap_or_else(|_| Normal::new(mean_ms as f64, 0.0).unwrap());
            let sample = dist.sample(&mut rand::rng());
            sample.round().clamp(0.0, MAX_DELAY_MS as f64) as u64
        }
        _ => mean_ms,
    }
}

pub(crate) fn validate_delay(delay: Option<u64>) -> Result<Option<u64>, &'static str> {
    match delay {
        Some(ms) if ms > MAX_DELAY_MS => Err("delay exceeds the 60000 ms limit"),
        value => Ok(value),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_delay_validation_rejects_values_above_limit() {
        assert_eq!(validate_delay(Some(MAX_DELAY_MS)), Ok(Some(MAX_DELAY_MS)));
        assert!(validate_delay(Some(MAX_DELAY_MS + 1)).is_err());
    }
}
