// SPDX-License-Identifier: Apache-2.0
//! Masking strategies: redact, partial, hash, tokenize, remove; span resolution and string building.

use sha2::{Digest, Sha256};
use std::borrow::Cow;
use std::collections::HashMap;
use uuid::Uuid;

use super::config::{MaskingStrategy, PIIConfig, PIIType};
use super::detector::Detection;
use super::error::MaskError;

/// Single span to mask (start, end, type, strategy, value reference).
struct MaskSpan<'a> {
    start: usize,
    end: usize,
    pii_type: PIIType,
    strategy: MaskingStrategy,
    value: &'a str,
}

/// Last `n` characters of `s` as a new String (one allocation).
#[inline]
fn last_n_chars(s: &str, n: usize) -> String {
    let start = s
        .char_indices()
        .rev()
        .nth(n.saturating_sub(1))
        .map(|(idx, _)| idx)
        .unwrap_or(0);
    s[start..].to_string()
}

pub(crate) fn validate_text_span(text: &str, start: usize, end: usize) -> Result<(), MaskError> {
    if start >= end || end > text.len() {
        return Err(MaskError::InvalidSpan {
            start,
            end,
            text_len: text.len(),
        });
    }
    if !text.is_char_boundary(start) || !text.is_char_boundary(end) {
        return Err(MaskError::InvalidUtf8Boundary { start, end });
    }
    Ok(())
}

pub(crate) fn resolve_overlaps<T, FStart, FEnd, FPrefer>(
    mut spans: Vec<T>,
    start: FStart,
    end: FEnd,
    prefer_replacement: FPrefer,
) -> Vec<T>
where
    FStart: Fn(&T) -> usize,
    FEnd: Fn(&T) -> usize,
    FPrefer: Fn(&T, &T) -> bool,
{
    spans.sort_by(|a, b| start(a).cmp(&start(b)).then_with(|| end(b).cmp(&end(a))));

    let mut selected: Vec<T> = Vec::new();
    for span in spans {
        if let Some(last) = selected.last_mut() {
            if start(&span) >= end(last) {
                selected.push(span);
            } else if prefer_replacement(&span, last) {
                *last = span;
            }
        } else {
            selected.push(span);
        }
    }

    selected
}

/// Apply masking to detected PII in text
///
/// # Arguments
/// * `text` - Original text containing PII
/// * `detections` - Map of PIIType to detected instances
/// * `config` - Configuration with masking preferences
///
/// # Returns
/// Masked text with PII replaced according to strategies
pub fn mask_pii<'a>(
    text: &'a str,
    detections: &HashMap<PIIType, Vec<Detection>>,
    config: &PIIConfig,
) -> Result<Cow<'a, str>, MaskError> {
    if detections.is_empty() {
        // Zero-copy optimization when no masking needed
        return Ok(Cow::Borrowed(text));
    }

    let spans: Vec<MaskSpan<'_>> = detections
        .iter()
        .flat_map(|(pii_type, items)| {
            items.iter().map(|d| MaskSpan {
                start: d.start,
                end: d.end,
                pii_type: *pii_type,
                strategy: d.mask_strategy,
                value: d.value.as_str(),
            })
        })
        .collect();

    for s in &spans {
        validate_text_span(text, s.start, s.end)?;
    }

    let selected = resolve_overlaps(
        spans,
        |span| span.start,
        |span| span.end,
        |candidate, incumbent| {
            let incumbent_len = incumbent.end - incumbent.start;
            let candidate_len = candidate.end - candidate.start;
            candidate_len > incumbent_len
        },
    );

    // Conservative estimate for worst-case expansion from fixed markers like
    // [HASH:xxxxxxxx] or [TOKEN:xxxxxxxx], with extra headroom to avoid reallocation.
    const MAX_REPLACEMENT_DELTA: usize = 80;
    let capacity_estimate = text.len() + selected.len().saturating_mul(MAX_REPLACEMENT_DELTA);
    let mut out = String::with_capacity(capacity_estimate);
    let mut cursor = 0usize;
    for s in &selected {
        out.push_str(&text[cursor..s.start]);
        let masked_value = apply_mask_strategy(s.value, s.pii_type, s.strategy, config);
        out.push_str(&masked_value);
        cursor = s.end;
    }
    out.push_str(&text[cursor..]);

    Ok(Cow::Owned(out))
}

/// Apply specific masking strategy to a value
fn apply_mask_strategy(
    value: &str,
    pii_type: PIIType,
    strategy: MaskingStrategy,
    config: &PIIConfig,
) -> String {
    let effective_strategy = effective_mask_strategy(pii_type, strategy, config);
    match effective_strategy {
        MaskingStrategy::Auto => {
            log::warn!(
                "Auto masking strategy was not resolved for {}; falling back to the default strategy for this PII type",
                pii_type.as_str()
            );
            apply_mask_strategy(
                value,
                pii_type,
                default_mask_strategy_for_pii(pii_type),
                config,
            )
        }
        MaskingStrategy::Redact => config.redaction_text.clone(),
        MaskingStrategy::Partial => partial_mask(value, pii_type, config),
        MaskingStrategy::Hash => hash_mask(value),
        MaskingStrategy::Tokenize => tokenize_mask(),
        MaskingStrategy::Remove => String::new(),
    }
}

/// Resolve the effective masking policy for a detection.
pub(crate) fn effective_mask_strategy(
    pii_type: PIIType,
    detection_strategy: MaskingStrategy,
    config: &PIIConfig,
) -> MaskingStrategy {
    match config.default_mask_strategy {
        MaskingStrategy::Auto => match detection_strategy {
            MaskingStrategy::Auto => default_mask_strategy_for_pii(pii_type),
            other => other,
        },
        override_strategy => override_strategy,
    }
}

fn default_mask_strategy_for_pii(pii_type: PIIType) -> MaskingStrategy {
    match pii_type {
        PIIType::Ssn
        | PIIType::Bsn
        | PIIType::CreditCard
        | PIIType::Email
        | PIIType::Phone
        | PIIType::BankAccount
        | PIIType::FullName
        | PIIType::UsAbaRoutingNumber
        | PIIType::UsZipCode
        | PIIType::UsEin
        | PIIType::UsItin => MaskingStrategy::Partial,
        PIIType::IpAddress
        | PIIType::DateOfBirth
        | PIIType::Passport
        | PIIType::DriverLicense
        | PIIType::MedicalRecord
        | PIIType::StreetAddress
        | PIIType::Custom => MaskingStrategy::Redact,
    }
}

/// Partial masking - show first/last characters based on PII type
fn partial_mask(value: &str, pii_type: PIIType, config: &PIIConfig) -> String {
    let char_count = value.chars().count();
    match pii_type {
        PIIType::Ssn => {
            if char_count >= 4 {
                format!("***-**-{}", last_n_chars(value, 4))
            } else {
                config.redaction_text.clone()
            }
        }

        PIIType::Bsn => {
            if char_count >= 4 {
                format!("*****{}", last_n_chars(value, 4))
            } else {
                config.redaction_text.clone()
            }
        }

        PIIType::CreditCard => {
            let digits_only: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
            if digits_only.chars().count() >= 4 {
                format!("****-****-****-{}", last_n_chars(&digits_only, 4))
            } else {
                config.redaction_text.clone()
            }
        }

        PIIType::Email => {
            if let Some(at_pos) = value.find('@') {
                let local = &value[..at_pos];
                let domain = &value[at_pos..];
                let (base_local, plus_tag) = local.split_once('+').unwrap_or((local, ""));
                let preserved_tag = if plus_tag.is_empty() {
                    String::new()
                } else {
                    format!("+{}", plus_tag)
                };
                let local_len = local.chars().count();
                if local_len > 2 {
                    let first = base_local.chars().next();
                    let last = base_local.chars().last();
                    match (first, last) {
                        (Some(f), Some(l)) => format!("{}***{}{}{}", f, l, preserved_tag, domain),
                        _ => format!("***{}", domain),
                    }
                } else {
                    format!("***{}{}", preserved_tag, domain)
                }
            } else {
                config.redaction_text.clone()
            }
        }

        PIIType::Phone => {
            let digits_only: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
            if digits_only.chars().count() >= 4 {
                format!("***-***-{}", last_n_chars(&digits_only, 4))
            } else {
                config.redaction_text.clone()
            }
        }

        PIIType::BankAccount => {
            if char_count >= 4 && value.chars().any(|c| c.is_ascii_alphabetic()) {
                let mut chars = value.chars();
                let first_two: String = chars.by_ref().take(2).collect();
                let stars = char_count.saturating_sub(6);
                format!(
                    "{}{}{}",
                    first_two,
                    "*".repeat(stars),
                    last_n_chars(value, 4)
                )
            } else {
                config.redaction_text.clone()
            }
        }

        _ => {
            if char_count > 2 {
                let first = value.chars().next().unwrap_or('*');
                let last = value.chars().last().unwrap_or('*');
                format!("{}{}{}", first, "*".repeat(char_count - 2), last)
            } else if char_count == 2 {
                let first = value.chars().next().unwrap_or('*');
                format!("{}*", first)
            } else {
                "*".to_string()
            }
        }
    }
}

/// Hash masking using SHA256
fn hash_mask(value: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    let result = hasher.finalize();
    format!("[HASH:{}]", &format!("{:x}", result)[..16])
}

/// Tokenize using UUID v4
fn tokenize_mask() -> String {
    let token = Uuid::new_v4();
    format!("[TOKEN:{}]", &token.simple().to_string()[..16])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_partial_mask_ssn() {
        let config = PIIConfig::default();
        let result = partial_mask("123-45-6789", PIIType::Ssn, &config);
        assert_eq!(result, "***-**-6789");
    }

    #[test]
    fn test_partial_mask_credit_card() {
        let config = PIIConfig::default();
        let result = partial_mask("4111-1111-1111-1111", PIIType::CreditCard, &config);
        assert_eq!(result, "****-****-****-1111");
    }

    #[test]
    fn test_partial_mask_email() {
        let config = PIIConfig::default();
        let result = partial_mask("john.doe@example.com", PIIType::Email, &config);
        assert!(result.contains("@example.com"));
        assert!(result.starts_with("j"));
    }

    #[test]
    fn test_partial_mask_email_non_ascii() {
        let config = PIIConfig::default();
        let result = partial_mask("jóse@example.com", PIIType::Email, &config);
        assert!(result.contains("@example.com"));
        // Should not panic and should keep 1st char visible.
        assert!(result.starts_with('j'));
        assert!(result.contains("***"));
    }

    #[test]
    fn test_hash_mask() {
        let result = hash_mask("sensitive");
        assert!(result.starts_with("[HASH:"));
        assert!(result.ends_with("]"));
        assert_eq!(result.len(), 23); // [HASH:xxxxxxxxxxxxxxxx]
    }

    #[test]
    fn test_tokenize_mask() {
        let result = tokenize_mask();
        assert!(result.starts_with("[TOKEN:"));
        assert!(result.ends_with("]"));
    }

    #[test]
    fn test_mask_pii_empty() {
        let config = PIIConfig::default();
        let detections = HashMap::new();
        let text = "No PII here";

        let result = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(result, text); // Zero-copy
    }

    #[test]
    fn test_mask_pii_invalid_span_raises_error() {
        let config = PIIConfig::default();
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Ssn,
            vec![Detection {
                value: "123-45-6789".to_string(),
                start: 5,
                end: 50,
                mask_strategy: MaskingStrategy::Redact,
                description: String::new(),
            }],
        );

        let err = mask_pii("short", &detections, &config).expect_err("invalid span should fail");
        assert!(matches!(err, MaskError::InvalidSpan { .. }));
    }

    #[test]
    fn test_mask_pii_overlap_prefer_longest() {
        let config = PIIConfig::default();
        let text = "abc12345def";

        // Overlapping spans: (3..8) and (3..10). Prefer the longer (3..10).
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Custom,
            vec![
                Detection {
                    value: "12345".to_string(),
                    start: 3,
                    end: 8,
                    mask_strategy: MaskingStrategy::Remove,
                    description: String::new(),
                },
                Detection {
                    value: "12345de".to_string(),
                    start: 3,
                    end: 10,
                    mask_strategy: MaskingStrategy::Redact,
                    description: String::new(),
                },
            ],
        );

        let masked = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(masked.as_ref(), "abc[REDACTED]f");
    }

    #[test]
    fn test_mask_pii_redact_strategy() {
        let config = PIIConfig {
            redaction_text: "[X]".to_string(),
            default_mask_strategy: MaskingStrategy::Redact,
            ..Default::default()
        };
        let text = "My SSN is 123-45-6789";
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Ssn,
            vec![Detection {
                value: "123-45-6789".to_string(),
                start: 10,
                end: 21,
                mask_strategy: MaskingStrategy::Redact,
                description: String::new(),
            }],
        );
        let masked = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(masked.as_ref(), "My SSN is [X]");
    }

    #[test]
    fn test_mask_pii_remove_strategy() {
        let config = PIIConfig {
            default_mask_strategy: MaskingStrategy::Remove,
            ..Default::default()
        };
        let text = "My SSN is 123-45-6789";
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Ssn,
            vec![Detection {
                value: "123-45-6789".to_string(),
                start: 10,
                end: 21,
                mask_strategy: MaskingStrategy::Remove,
                description: String::new(),
            }],
        );
        let masked = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(masked.as_ref(), "My SSN is ");
    }

    #[test]
    fn test_effective_mask_strategy_respects_default_override() {
        let config = PIIConfig {
            default_mask_strategy: MaskingStrategy::Hash,
            ..Default::default()
        };
        assert_eq!(
            effective_mask_strategy(PIIType::Ssn, MaskingStrategy::Partial, &config),
            MaskingStrategy::Hash
        );
    }

    #[test]
    fn test_effective_mask_strategy_uses_detection_strategy_in_default_mode() {
        let config = PIIConfig::default();
        assert_eq!(
            effective_mask_strategy(PIIType::Ssn, MaskingStrategy::Partial, &config),
            MaskingStrategy::Partial
        );
    }

    #[test]
    fn test_mask_pii_unresolved_auto_falls_back_without_panicking() {
        let config = PIIConfig {
            default_mask_strategy: MaskingStrategy::Auto,
            ..Default::default()
        };
        let text = "My SSN is 123-45-6789";
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Ssn,
            vec![Detection {
                value: "123-45-6789".to_string(),
                start: 10,
                end: 21,
                mask_strategy: MaskingStrategy::Auto,
                description: String::new(),
            }],
        );

        let masked = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(masked.as_ref(), "My SSN is ***-**-6789");
    }

    #[test]
    fn test_mask_pii_invalid_utf8_boundary() {
        let config = PIIConfig::default();
        // "é" is 2 bytes in UTF-8 (0xC3 0xA9). Span (0..1) splits it.
        let text = "é";
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Custom,
            vec![Detection {
                value: "".to_string(),
                start: 0,
                end: 1,
                mask_strategy: MaskingStrategy::Redact,
                description: String::new(),
            }],
        );
        let result = mask_pii(text, &detections, &config);
        assert!(matches!(
            result,
            Err(MaskError::InvalidUtf8Boundary { start: 0, end: 1 })
        ));
    }

    #[test]
    fn test_mask_pii_multiple_non_overlapping_spans() {
        let config = PIIConfig::default();
        let text = "SSN: 123-45-6789 and email: john@example.com";
        let mut detections: HashMap<PIIType, Vec<Detection>> = HashMap::new();
        detections.insert(
            PIIType::Ssn,
            vec![Detection {
                value: "123-45-6789".to_string(),
                start: 5,
                end: 16,
                mask_strategy: MaskingStrategy::Redact,
                description: String::new(),
            }],
        );
        detections.insert(
            PIIType::Email,
            vec![Detection {
                value: "john@example.com".to_string(),
                start: 28,
                end: 44,
                mask_strategy: MaskingStrategy::Redact,
                description: String::new(),
            }],
        );
        let masked = mask_pii(text, &detections, &config).unwrap();
        assert_eq!(masked.as_ref(), "SSN: [REDACTED] and email: [REDACTED]");
    }
}
