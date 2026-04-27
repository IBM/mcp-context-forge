// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! HCS-14 Universal Agent ID (UAID) parsing and routing for the A2A runtime.
//!
//! This module is the A2A-1.0-flavoured counterpart to the Python
//! `mcpgateway/utils/uaid.py`.  The wire contract differs from Python's
//! ContextForge-to-ContextForge federation path: Rust resolves the UAID's
//! `nativeId` to an A2A agent URL and POSTs the original JSON-RPC 2.0
//! request body there, with no gateway indirection.
//!
//! Format:
//! ```text
//! uaid:aid:{base58-hash};uid={uid};registry={registry};proto={proto};nativeId={endpoint}
//! uaid:did:{did};uid={uid};proto={proto};nativeId={endpoint}
//! ```
//!
//! `nativeId` here may be either a plain hostname (optionally with `:port`)
//! or a full `http(s)://host[:port][/path]` URL — the latter matches how
//! A2A agents advertise their endpoints in their AgentCards.

use std::collections::HashMap;
use std::str::FromStr;
use thiserror::Error;
use url::Url;

/// Parsed UAID components.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UaidComponents {
    pub method: String,
    pub hash_or_did: String,
    pub uid: String,
    pub registry: Option<String>,
    pub proto: String,
    pub native_id: String,
}

/// Validated cross-gateway protocols this runtime can dispatch directly.
///
/// Parsing a UAID produces a free-form `proto` string (HCS-14 does not
/// fix the vocabulary); conversion to this enum happens inside
/// `resolve_routing` and is the single gate that decides whether the
/// runtime can speak the protocol or must reject it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Proto {
    /// A2A 1.0 JSON-RPC 2.0 over HTTP(S).
    A2a,
    /// MCP (accepted by the parser but the A2A runtime itself rejects
    /// it at dispatch time — kept so a future MCP sidecar can share
    /// this module).
    Mcp,
}

impl Proto {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::A2a => "a2a",
            Self::Mcp => "mcp",
        }
    }
}

impl FromStr for Proto {
    type Err = UaidError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "a2a" => Ok(Self::A2a),
            "mcp" => Ok(Self::Mcp),
            other => Err(UaidError::UnsupportedProtocol(other.to_string())),
        }
    }
}

/// Resolved routing target: a validated URL to POST a JSON-RPC request
/// to, paired with the protocol the caller selected.
///
/// Fields are private so the SSRF / scheme / allowlist gates in
/// [`resolve_routing`] cannot be bypassed by constructing a target
/// directly.  Accessors expose the validated data.
#[derive(Debug, Clone)]
pub struct RoutingTarget {
    protocol: Proto,
    url: Url,
    registry: Option<String>,
}

impl RoutingTarget {
    pub fn protocol(&self) -> Proto {
        self.protocol
    }

    pub fn url(&self) -> &Url {
        &self.url
    }

    pub fn registry(&self) -> Option<&str> {
        self.registry.as_deref()
    }
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum UaidError {
    #[error("UAID exceeds maximum length of {max} characters (got {got})")]
    TooLong { max: usize, got: usize },
    #[error("UAID contains ASCII control characters and cannot be parsed")]
    ControlChars,
    #[error("invalid UAID: must start with 'uaid:aid:' or 'uaid:did:'")]
    BadPrefix,
    #[error("invalid UAID method: expected 'aid' or 'did', got '{0}'")]
    BadMethod(String),
    #[error("invalid UAID: expected hash/did segment followed by ';key=value' parameters")]
    MissingParams,
    #[error("invalid UAID parameter: expected 'key=value' format, got '{0}'")]
    BadParam(String),
    #[error("invalid UAID: missing required parameter '{0}'")]
    MissingRequired(&'static str),
    #[error("invalid UAID: 'registry' is required for aid method")]
    MissingRegistry,
    #[error("nativeId contains '@' character (SSRF protection)")]
    NativeIdUserInfo,
    #[error("nativeId hostname is empty or unparseable")]
    NativeIdBadHost,
    #[error("unsupported URL scheme in nativeId: '{0}' (only http/https allowed)")]
    UnsupportedScheme(String),
    #[error("endpoint domain '{0}' not in allowlist")]
    DomainNotAllowed(String),
    #[error("unsupported protocol in UAID: '{0}'")]
    UnsupportedProtocol(String),
}

impl UaidError {
    /// Stable short identifier for structured logs and metrics.  The
    /// `Display` impl above is for humans; this is for greppable log
    /// fields and forensics (an `NativeIdUserInfo` entry in the logs
    /// is a direct attack signal operators will want to count).
    pub fn code(&self) -> &'static str {
        match self {
            Self::TooLong { .. } => "too_long",
            Self::ControlChars => "control_chars",
            Self::BadPrefix => "bad_prefix",
            Self::BadMethod(_) => "bad_method",
            Self::MissingParams => "missing_params",
            Self::BadParam(_) => "bad_param",
            Self::MissingRequired(_) => "missing_required",
            Self::MissingRegistry => "missing_registry",
            Self::NativeIdUserInfo => "native_id_user_info",
            Self::NativeIdBadHost => "native_id_bad_host",
            Self::UnsupportedScheme(_) => "unsupported_scheme",
            Self::DomainNotAllowed(_) => "domain_not_allowed",
            Self::UnsupportedProtocol(_) => "unsupported_protocol",
        }
    }
}

/// Returns true iff `s` has a UAID prefix.  Cheap — used as a dispatch
/// predicate before paying the cost of a full parse.
pub fn is_uaid(s: &str) -> bool {
    s.starts_with("uaid:aid:") || s.starts_with("uaid:did:")
}

/// Parse a UAID string into its components.  Enforces the DoS length cap
/// before doing any other work.
pub fn parse_uaid(uaid: &str, max_length: usize) -> Result<UaidComponents, UaidError> {
    if uaid.len() > max_length {
        return Err(UaidError::TooLong {
            max: max_length,
            got: uaid.len(),
        });
    }
    // Defense-in-depth: reject ASCII control characters (including CR, LF,
    // NUL, and DEL).  A UAID that carries CRLF is a log-injection or
    // header-smuggling vector — rejecting here means even non-log code
    // paths cannot treat such a UAID as valid.  Mirrors the matching
    // check in Python's `mcpgateway/utils/uaid.py::parse_uaid`.
    if uaid.bytes().any(|b| b < 0x20 || b == 0x7F) {
        return Err(UaidError::ControlChars);
    }
    if !is_uaid(uaid) {
        return Err(UaidError::BadPrefix);
    }

    // Split only on the first two colons so port numbers in nativeId (e.g.
    // `gateway.example.com:8443`) survive.
    let mut parts = uaid.splitn(3, ':');
    let _ = parts.next();
    let method = parts.next().ok_or(UaidError::BadPrefix)?;
    let remainder = parts.next().ok_or(UaidError::BadPrefix)?;

    if method != "aid" && method != "did" {
        return Err(UaidError::BadMethod(method.to_string()));
    }

    let mut segments = remainder.split(';');
    let hash_or_did = segments.next().ok_or(UaidError::MissingParams)?.to_string();
    if hash_or_did.is_empty() {
        return Err(UaidError::MissingParams);
    }

    let mut params: HashMap<&str, &str> = HashMap::new();
    let mut saw_any_param = false;
    for seg in segments {
        saw_any_param = true;
        let (k, v) = seg
            .split_once('=')
            .ok_or_else(|| UaidError::BadParam(seg.to_string()))?;
        params.insert(k, v);
    }
    if !saw_any_param {
        return Err(UaidError::MissingParams);
    }

    let uid = params
        .get("uid")
        .ok_or(UaidError::MissingRequired("uid"))?
        .to_string();
    let proto = params
        .get("proto")
        .ok_or(UaidError::MissingRequired("proto"))?
        .to_string();
    let native_id = params
        .get("nativeId")
        .ok_or(UaidError::MissingRequired("nativeId"))?
        .to_string();
    let registry = params.get("registry").map(|s| s.to_string());

    if method == "aid" && registry.as_deref().map(str::is_empty).unwrap_or(true) {
        return Err(UaidError::MissingRegistry);
    }

    Ok(UaidComponents {
        method: method.to_string(),
        hash_or_did,
        uid,
        registry,
        proto,
        native_id,
    })
}

/// Return true iff `host` equals one of `allowed_domains` or is a proper
/// subdomain of one (`host.endswith(".domain")`).  Matches the semantics
/// of the Python allowlist check — rejects suffix-bypass attacks like
/// `evilexample.com` vs `example.com`.  Comparison is case-insensitive
/// because DNS hostnames are.  `pub(crate)` because the only sanctioned
/// call site is `resolve_routing` — direct callers would bypass scheme
/// and user-info validation.
pub(crate) fn endpoint_allowed(host: &str, allowed_domains: &[String]) -> bool {
    if allowed_domains.is_empty() {
        return true; // Unsafe default, logged upstream.
    }
    let host = host.to_ascii_lowercase();
    allowed_domains.iter().any(|d| {
        let d = d.trim().trim_start_matches('.').to_ascii_lowercase();
        host == d || host.ends_with(&format!(".{d}"))
    })
}

/// Build a validated [`RoutingTarget`] from a parsed UAID and an allowlist.
///
/// `nativeId` may be either a plain hostname (optionally with `:port`) or a
/// full `http(s)://host[:port][/path]` URL.  In the hostname-only case the
/// target URL is `https://{nativeId}/` — the root path, matching the A2A
/// 1.0 convention where an agent's service endpoint is the URL published
/// in its AgentCard.
pub fn resolve_routing(
    components: &UaidComponents,
    allowed_domains: &[String],
) -> Result<RoutingTarget, UaidError> {
    let proto = Proto::from_str(components.proto.as_str())?;

    let native = components.native_id.trim();
    if native.contains('@') {
        return Err(UaidError::NativeIdUserInfo);
    }

    // Parse nativeId. Accept a full URL or a hostname[:port].
    let url = if native.starts_with("http://") || native.starts_with("https://") {
        let parsed = Url::parse(native).map_err(|_| UaidError::NativeIdBadHost)?;
        match parsed.scheme() {
            "http" | "https" => {}
            other => return Err(UaidError::UnsupportedScheme(other.to_string())),
        }
        if parsed.host_str().unwrap_or("").is_empty() {
            return Err(UaidError::NativeIdBadHost);
        }
        parsed
    } else {
        // Hostname-only form: reject any path/query/fragment characters.
        // `/` and `?` and `#` are disallowed so SSRF via path injection
        // (`host/admin`) cannot smuggle through.
        if native.contains('/') || native.contains('?') || native.contains('#') {
            return Err(UaidError::NativeIdBadHost);
        }
        let candidate = format!("https://{native}/");
        let parsed = Url::parse(&candidate).map_err(|_| UaidError::NativeIdBadHost)?;
        if parsed.host_str().unwrap_or("").is_empty() {
            return Err(UaidError::NativeIdBadHost);
        }
        parsed
    };

    let host = url.host_str().unwrap_or("").to_string();
    if !endpoint_allowed(&host, allowed_domains) {
        return Err(UaidError::DomainNotAllowed(host));
    }

    Ok(RoutingTarget {
        protocol: proto,
        url,
        registry: components.registry.clone(),
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const VALID_AID: &str =
        "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com";
    const MAX: usize = 2048;

    fn parse_ok(s: &str) -> UaidComponents {
        parse_uaid(s, MAX).expect("valid UAID")
    }

    #[test]
    fn is_uaid_matches_aid_and_did_prefixes() {
        assert!(is_uaid(
            "uaid:aid:abc;uid=0;registry=x;proto=a2a;nativeId=h"
        ));
        assert!(is_uaid("uaid:did:abc;uid=0;proto=a2a;nativeId=h"));
        assert!(!is_uaid("uuid:abc"));
        assert!(!is_uaid("uaid:other:abc"));
    }

    #[test]
    fn parse_valid_aid_uaid_with_port_in_native_id() {
        let c =
            parse_ok("uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=gateway.example.com:8443");
        assert_eq!(c.method, "aid");
        assert_eq!(c.hash_or_did, "HASH");
        assert_eq!(c.uid, "0");
        assert_eq!(c.registry.as_deref(), Some("cf"));
        assert_eq!(c.proto, "a2a");
        assert_eq!(c.native_id, "gateway.example.com:8443");
    }

    #[test]
    fn parse_did_uaid_does_not_require_registry() {
        let c = parse_ok("uaid:did:did:web:example;uid=0;proto=a2a;nativeId=h.example.com");
        assert_eq!(c.method, "did");
        assert_eq!(c.registry, None);
    }

    #[test]
    fn parse_rejects_missing_required_params() {
        let err = parse_uaid("uaid:aid:H;uid=0;registry=cf;proto=a2a", MAX).unwrap_err();
        assert_eq!(err, UaidError::MissingRequired("nativeId"));

        let err = parse_uaid("uaid:aid:H;uid=0;proto=a2a;nativeId=h", MAX).unwrap_err();
        assert_eq!(err, UaidError::MissingRegistry);
    }

    #[test]
    fn parse_rejects_bad_prefix_and_method() {
        assert_eq!(parse_uaid("nope", MAX).unwrap_err(), UaidError::BadPrefix);
        // `uaid:xyz:rest` fails is_uaid (prefix check) before the method
        // comparison, so this surfaces as BadPrefix.
        assert_eq!(
            parse_uaid("uaid:xyz:rest;uid=0;proto=a2a;nativeId=h", MAX).unwrap_err(),
            UaidError::BadPrefix
        );
    }

    #[test]
    fn parse_rejects_malformed_params() {
        let err = parse_uaid("uaid:aid:H;noequals;proto=a2a;nativeId=h", MAX).unwrap_err();
        assert!(matches!(err, UaidError::BadParam(_)));
    }

    #[test]
    fn parse_rejects_oversized_input() {
        let long = format!("uaid:aid:{}", "x".repeat(3000));
        let err = parse_uaid(&long, MAX).unwrap_err();
        assert!(matches!(err, UaidError::TooLong { .. }));
    }

    #[test]
    fn parse_rejects_ascii_control_characters() {
        // CR and LF are the log-injection vectors we care about most, but
        // the check covers every byte < 0x20 plus 0x7F.  Testing a
        // representative cross-section is enough to catch regressions.
        for injected in ["\n", "\r", "\r\n", "\x00", "\t", "\x7f"] {
            let uaid = format!(
                "uaid:aid:HASH{injected};uid=0;registry=cf;proto=a2a;nativeId=agent.example.com"
            );
            assert_eq!(
                parse_uaid(&uaid, MAX).unwrap_err(),
                UaidError::ControlChars,
                "expected ControlChars rejection for byte {:?}",
                injected
            );
        }
    }

    #[test]
    fn endpoint_allowed_exact_and_subdomain_match() {
        let list = vec!["example.com".to_string()];
        assert!(endpoint_allowed("example.com", &list));
        assert!(endpoint_allowed("sub.example.com", &list));
        assert!(endpoint_allowed("a.b.example.com", &list));
        // Suffix-bypass attacks must be rejected.
        assert!(!endpoint_allowed("evilexample.com", &list));
        assert!(!endpoint_allowed("example.com.evil.net", &list));
        assert!(!endpoint_allowed("other.org", &list));
    }

    #[test]
    fn endpoint_allowed_empty_list_permits_all() {
        assert!(endpoint_allowed("any.host", &[]));
    }

    #[test]
    fn resolve_routing_builds_https_url_from_hostname_only_native_id() {
        let c = parse_ok(VALID_AID);
        let t = resolve_routing(&c, &[]).unwrap();
        assert_eq!(t.protocol(), Proto::A2a);
        assert_eq!(t.url().scheme(), "https");
        assert_eq!(t.url().host_str(), Some("agent.example.com"));
        assert_eq!(t.url().path(), "/");
    }

    #[test]
    fn resolve_routing_accepts_full_url_native_id() {
        let uaid =
            "uaid:aid:H;uid=0;registry=cf;proto=a2a;nativeId=https://agent.example.com/a2a/send";
        let c = parse_ok(uaid);
        let t = resolve_routing(&c, &[]).unwrap();
        assert_eq!(t.url().scheme(), "https");
        assert_eq!(t.url().host_str(), Some("agent.example.com"));
        assert_eq!(t.url().path(), "/a2a/send");
    }

    #[test]
    fn resolve_routing_rejects_user_info_in_native_id() {
        let uaid = "uaid:aid:H;uid=0;registry=cf;proto=a2a;nativeId=evil@127.0.0.1";
        let c = parse_ok(uaid);
        assert_eq!(
            resolve_routing(&c, &[]).unwrap_err(),
            UaidError::NativeIdUserInfo
        );
    }

    #[test]
    fn resolve_routing_rejects_path_in_hostname_only_form() {
        let uaid = "uaid:aid:H;uid=0;registry=cf;proto=a2a;nativeId=agent.example.com/admin";
        let c = parse_ok(uaid);
        assert_eq!(
            resolve_routing(&c, &[]).unwrap_err(),
            UaidError::NativeIdBadHost
        );
    }

    #[test]
    fn resolve_routing_rejects_non_http_scheme() {
        let uaid = "uaid:aid:H;uid=0;registry=cf;proto=a2a;nativeId=ftp://agent.example.com";
        let c = parse_ok(uaid);
        match resolve_routing(&c, &[]).unwrap_err() {
            UaidError::NativeIdBadHost | UaidError::UnsupportedScheme(_) => {}
            other => panic!("expected scheme rejection, got {other:?}"),
        }
    }

    #[test]
    fn resolve_routing_enforces_allowlist() {
        let uaid = "uaid:aid:H;uid=0;registry=cf;proto=a2a;nativeId=blocked.com";
        let c = parse_ok(uaid);
        let err = resolve_routing(&c, &["allowed.com".to_string()]).unwrap_err();
        assert_eq!(err, UaidError::DomainNotAllowed("blocked.com".to_string()));
    }

    #[test]
    fn resolve_routing_rejects_unsupported_protocol() {
        let uaid = "uaid:aid:H;uid=0;registry=cf;proto=ftp;nativeId=agent.example.com";
        let c = parse_ok(uaid);
        assert_eq!(
            resolve_routing(&c, &[]).unwrap_err(),
            UaidError::UnsupportedProtocol("ftp".to_string())
        );
    }

    /// Exhaustiveness guard for `Proto`: every variant must round-trip
    /// via `as_str` → `FromStr`.  If someone adds a new variant without
    /// updating either side, this test fails to compile (on the `match`)
    /// or fails at runtime (on the round-trip), surfacing the drift.
    #[test]
    fn proto_from_str_and_as_str_round_trip_every_variant() {
        for proto in [Proto::A2a, Proto::Mcp] {
            // The match is the compile-time exhaustiveness check — if a
            // new variant is added, this match stops compiling.
            let expected_str = match proto {
                Proto::A2a => "a2a",
                Proto::Mcp => "mcp",
            };
            assert_eq!(proto.as_str(), expected_str);
            let parsed: Proto = expected_str.parse().expect("variant must parse");
            assert_eq!(parsed, proto);
        }
    }

    #[test]
    fn proto_from_str_rejects_unknown() {
        let err: UaidError = "ftp".parse::<Proto>().unwrap_err();
        assert_eq!(err, UaidError::UnsupportedProtocol("ftp".to_string()));
    }

    /// Stability contract for `UaidError::code()`.  The strings are a
    /// log-grep / metrics-dashboard API surface: renaming any of them
    /// silently breaks operator tooling.  Keep this assertion in lockstep
    /// with any intentional change to `code()`.
    #[test]
    fn uaid_error_codes_are_stable() {
        let cases: &[(UaidError, &str)] = &[
            (UaidError::TooLong { max: 1, got: 2 }, "too_long"),
            (UaidError::ControlChars, "control_chars"),
            (UaidError::BadPrefix, "bad_prefix"),
            (UaidError::BadMethod("x".to_string()), "bad_method"),
            (UaidError::MissingParams, "missing_params"),
            (UaidError::BadParam("x".to_string()), "bad_param"),
            (UaidError::MissingRequired("uid"), "missing_required"),
            (UaidError::MissingRegistry, "missing_registry"),
            (UaidError::NativeIdUserInfo, "native_id_user_info"),
            (UaidError::NativeIdBadHost, "native_id_bad_host"),
            (
                UaidError::UnsupportedScheme("x".to_string()),
                "unsupported_scheme",
            ),
            (
                UaidError::DomainNotAllowed("x".to_string()),
                "domain_not_allowed",
            ),
            (
                UaidError::UnsupportedProtocol("x".to_string()),
                "unsupported_protocol",
            ),
        ];
        for (err, expected) in cases {
            assert_eq!(err.code(), *expected, "code drift on {err:?}");
        }
    }
}
