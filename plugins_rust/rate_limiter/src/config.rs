// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Configuration types for the rate limiter engine.
//
// All rate strings are parsed once at engine init (`RateLimiterEngine::new`).
// The `by_tool` map is normalised (strip + lowercase) at init — never on the
// request path (IFACE-01, IFACE-05).

use std::collections::HashMap;
use thiserror::Error;

/// A parsed rate limit: `count` requests per `window_nanos` nanoseconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RateLimit {
    pub count: u64,
    pub window_nanos: u64,
}

/// Errors that can occur while parsing config.
#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("invalid rate string {0:?}: expected \"<count>/<unit>\" where unit is s/m/h")]
    InvalidRateString(String),
    #[error("rate count must be > 0, got {0}")]
    ZeroCount(u64),
    #[error(
        "invalid algorithm {0:?}: expected \"fixed_window\", \"sliding_window\", or \"token_bucket\""
    )]
    InvalidAlgorithm(String),
}

/// Parse a rate string like `"30/m"`, `"100/s"`, `"1000/h"`.
///
/// Accepted units (case-insensitive): `s`, `sec`, `second`, `m`, `min`,
/// `minute`, `h`, `hr`, `hour`.
pub fn parse_rate(s: &str) -> Result<RateLimit, ConfigError> {
    let s = s.trim();
    let (count_str, unit_str) = s
        .split_once('/')
        .ok_or_else(|| ConfigError::InvalidRateString(s.to_string()))?;

    let count: u64 = count_str
        .trim()
        .parse()
        .map_err(|_| ConfigError::InvalidRateString(s.to_string()))?;

    if count == 0 {
        return Err(ConfigError::ZeroCount(count));
    }

    let window_secs: u64 = match unit_str.trim().to_ascii_lowercase().as_str() {
        "s" | "sec" | "second" => 1,
        "m" | "min" | "minute" => 60,
        "h" | "hr" | "hour" => 3600,
        _ => return Err(ConfigError::InvalidRateString(s.to_string())),
    };

    Ok(RateLimit {
        count,
        window_nanos: window_secs * 1_000_000_000,
    })
}

/// Which counting algorithm to use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Algorithm {
    FixedWindow,
    SlidingWindow,
    TokenBucket,
}

impl Algorithm {
    /// Parse an algorithm name from a string.
    #[allow(clippy::should_implement_trait)]
    pub fn from_str(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "fixed_window" => Some(Self::FixedWindow),
            "sliding_window" => Some(Self::SlidingWindow),
            "token_bucket" => Some(Self::TokenBucket),
            _ => None,
        }
    }
}

/// Validated engine configuration, built from the raw Python dict.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub by_user: Option<RateLimit>,
    pub by_tenant: Option<RateLimit>,
    /// Normalised key → limit. Keys are already `.trim().to_lowercase()`.
    pub by_tool: HashMap<String, RateLimit>,
    pub algorithm: Algorithm,
}

impl EngineConfig {
    /// Build from raw string fields (mirrors the Python `RateLimiterConfig` fields
    /// that are relevant to the Rust engine — strict subset per IFACE-04).
    pub fn new(
        by_user: Option<&str>,
        by_tenant: Option<&str>,
        by_tool: HashMap<String, String>,
        algorithm: &str,
    ) -> Result<Self, ConfigError> {
        let by_user = by_user.map(parse_rate).transpose()?;
        let by_tenant = by_tenant.map(parse_rate).transpose()?;
        let by_tool = by_tool
            .into_iter()
            .map(|(k, v)| {
                let normalised_key = k.trim().to_ascii_lowercase();
                parse_rate(&v).map(|limit| (normalised_key, limit))
            })
            .collect::<Result<HashMap<_, _>, _>>()?;
        let algorithm = Algorithm::from_str(algorithm)
            .ok_or_else(|| ConfigError::InvalidAlgorithm(algorithm.to_string()))?;
        Ok(Self {
            by_user,
            by_tenant,
            by_tool,
            algorithm,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- parse_rate ---

    #[test]
    fn parse_rate_seconds_short() {
        let r = parse_rate("10/s").unwrap();
        assert_eq!(r.count, 10);
        assert_eq!(r.window_nanos, 1_000_000_000);
    }

    #[test]
    fn parse_rate_minutes_short() {
        let r = parse_rate("30/m").unwrap();
        assert_eq!(r.count, 30);
        assert_eq!(r.window_nanos, 60 * 1_000_000_000);
    }

    #[test]
    fn parse_rate_hours_long() {
        let r = parse_rate("1000/hour").unwrap();
        assert_eq!(r.count, 1000);
        assert_eq!(r.window_nanos, 3600 * 1_000_000_000);
    }

    #[test]
    fn parse_rate_whitespace_stripped() {
        let r = parse_rate("  5 / min  ").unwrap();
        assert_eq!(r.count, 5);
    }

    #[test]
    fn parse_rate_unsupported_unit_errors() {
        assert!(parse_rate("10/day").is_err());
    }

    #[test]
    fn parse_rate_no_slash_errors() {
        assert!(parse_rate("10m").is_err());
    }

    #[test]
    fn parse_rate_zero_count_errors() {
        assert!(parse_rate("0/s").is_err());
    }

    // --- Algorithm::from_str ---

    #[test]
    fn algorithm_from_str_all_variants() {
        assert_eq!(
            Algorithm::from_str("fixed_window"),
            Some(Algorithm::FixedWindow)
        );
        assert_eq!(
            Algorithm::from_str("sliding_window"),
            Some(Algorithm::SlidingWindow)
        );
        assert_eq!(
            Algorithm::from_str("token_bucket"),
            Some(Algorithm::TokenBucket)
        );
        assert_eq!(Algorithm::from_str("unknown"), None);
    }

    // --- EngineConfig ---

    #[test]
    fn engine_config_parses_all_fields() {
        let mut by_tool = HashMap::new();
        by_tool.insert("Search".to_string(), "10/m".to_string());
        by_tool.insert("  Summarise  ".to_string(), "5/m".to_string());

        let cfg = EngineConfig::new(Some("30/m"), Some("300/m"), by_tool, "fixed_window").unwrap();

        assert_eq!(cfg.by_user.unwrap().count, 30);
        assert_eq!(cfg.by_tenant.unwrap().count, 300);
        // Keys must be normalised
        assert!(cfg.by_tool.contains_key("search"));
        assert!(cfg.by_tool.contains_key("summarise"));
        assert!(!cfg.by_tool.contains_key("Search"));
        assert_eq!(cfg.algorithm, Algorithm::FixedWindow);
    }

    #[test]
    fn engine_config_all_none_is_valid() {
        let cfg = EngineConfig::new(None, None, HashMap::new(), "sliding_window").unwrap();
        assert!(cfg.by_user.is_none());
        assert!(cfg.by_tenant.is_none());
        assert!(cfg.by_tool.is_empty());
    }

    #[test]
    fn engine_config_invalid_rate_propagates_error() {
        assert!(EngineConfig::new(Some("bad"), None, HashMap::new(), "fixed_window").is_err());
    }

    #[test]
    fn engine_config_invalid_algorithm_propagates_error() {
        assert!(EngineConfig::new(None, None, HashMap::new(), "leaky_bucket").is_err());
    }
}
