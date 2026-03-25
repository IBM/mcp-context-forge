# PII Filter (Rust)

High-performance PII detection and masking library for ContextForge.

## Features

- Detects 12+ PII types (SSN, email, credit cards, phone numbers, AWS keys, etc.)
- Multiple masking strategies (partial, hash, tokenize, remove)
- Parallel regex matching with RegexSet (5-10x faster than Python)
- Zero-copy operations for nested JSON/dict traversal
- Whitelist support for false positive filtering
- Deterministic overlap resolution: earliest match wins, then the longest match wins
- Structural validation for SSNs and common card issuer ranges to reduce false positives
- Explicit guardrails for oversized inputs and pathological custom patterns

## Build

```bash
make install
```

## Usage

The Rust implementation is automatically used by the Python PII filter plugin when available.

## Detection Coverage

This section describes the current Rust detector behavior so users know what is intentionally matched and what is intentionally left alone. The detector is optimized to reduce noisy false positives, which means some generic identifiers are only matched when they appear with clear context labels.

### Social Security Numbers (SSN)

**Covers**
- Dashed US SSNs such as `123-45-6789`
- Compact 9-digit SSNs only when they appear with SSN-specific context such as `SSN`, `Social Security`, or `Social Security Number`
- Structural validation that rejects impossible values such as `000-12-3456`, `666-12-3456`, `123-00-4567`, and `123-45-0000`

**Does not cover**
- Bare 9-digit values without SSN context
- Real-world identity verification or SSA-backed validation
- Country-specific national identifiers outside the US SSN patterns

### BSN (Dutch Citizen Service Number)

**Covers**
- 9-digit BSNs when they appear with explicit Dutch/BSN-style context such as `BSN`, `Citizen ID`, `Citizen Service Number`, or `Burgerservicenummer`
- Phrases such as `My BSN is 123456789`

**Does not cover**
- Generic unlabeled 9-digit numbers
- Generic business identifiers such as order numbers, invoice numbers, or tracking numbers unless they also use BSN-specific wording
- Validation against authoritative Dutch registries

### Credit Card Numbers

**Covers**
- Common 13-19 digit card numbers with spaces or dashes
- Luhn-valid numbers from the major issuer families currently recognized by the detector, including Visa, Mastercard, American Express, Discover, Diners Club, JCB, UnionPay, and Maestro

**Does not cover**
- Numbers that fail Luhn validation
- Arbitrary long digit strings that do not match a recognized card-prefix family
- Full issuer-specific business rules beyond prefix and Luhn checks

### Email Addresses

**Covers**
- Standard email addresses such as `alice@example.com`
- Partial masking that preserves enough structure for debugging, for example `a***e@example.com`

**Does not cover**
- Full RFC-complete email parsing
- Mailbox ownership verification or domain reachability checks
- Obfuscated emails such as `alice at example dot com`

### Phone Numbers

**Covers**
- Common US phone number formats such as `555-123-4567`, `(555) 123-4567`, and `1 555 123 4567`
- International numbers with an explicit leading `+` and enough digits to look like an E.164-style value

**Does not cover**
- Short local extensions or ambiguous local-only numbers
- International numbers without a leading `+`
- Country-by-country numbering-plan validation

### IP Addresses

**Covers**
- Standard IPv4 dotted-quad addresses
- Fully expanded IPv6 addresses in the eight-group hexadecimal form

**Does not cover**
- Shorthand IPv6 forms such as `2001:db8::1`
- Hostnames, URLs, or CIDR ranges
- Private/public classification or network reachability checks

### Dates of Birth

**Covers**
- Explicitly labeled date-of-birth phrases such as `DOB: 01/15/1990`
- Unlabeled dates in `MM/DD/YYYY` or `MM-DD-YYYY` form within the configured year range

**Does not cover**
- Locale-specific date parsing beyond the built-in patterns
- Natural-language dates such as `15 January 1990`
- Any proof that a matched date is actually a birth date when no DOB-style label is present

### Passport Numbers

**Covers**
- Passport identifiers only when they appear with explicit passport context such as `Passport`, `Passport No`, or `Passport Number`
- Label-plus-value matches such as `Passport Number: AB123456`

**Does not cover**
- Standalone alphanumeric IDs without passport wording
- Country-specific passport validation rules
- Broader travel-document types that do not use passport labels

### Driver's License Numbers

**Covers**
- Driver's license values with explicit labels such as `DL`, `License`, or `Driver's License`

**Does not cover**
- Unlabeled alphanumeric identifiers
- State-by-state or country-by-country license validation rules
- Vehicle registration numbers or other transport-related IDs

### Bank Account Numbers

**Covers**
- Account numbers when they appear with explicit account-style context such as `Account`, `Acct`, `Bank Account`, or `Account Number`
- IBAN-like values that match the built-in pattern

**Does not cover**
- Bare 8-17 digit values without account context
- Full IBAN country validation or checksum verification
- Routing-number-only detection

### Medical Record Numbers

**Covers**
- Explicitly labeled medical record identifiers such as `MRN` or `Medical Record`

**Does not cover**
- Unlabeled healthcare identifiers
- Insurance member IDs, prescription IDs, or other healthcare-adjacent identifiers unless added through custom patterns
- Validation against provider or hospital systems

### Custom Patterns

**Covers**
- User-defined regex patterns for organization-specific identifiers
- Explicit per-pattern masking strategies
- Guardrails that reject patterns that are too long or too complex for maintainable admin-authored configuration

**Does not cover**
- Unlimited regex expressiveness
- Automatic tuning of custom patterns for precision or recall
- Protection against poor pattern choices that are syntactically valid but semantically too broad

Custom patterns are intended for trusted operators editing plugin configuration, not untrusted end-user input. The Rust implementation relies on the [`regex`](https://docs.rs/regex/latest/regex/) crate, which avoids catastrophic backtracking during matching, and then applies additional length and complexity limits to keep custom expressions readable and cheap to compile.

## Secret Detection

The Rust plugin also detects AWS keys and generic API-key style assignments, but secret formats tend to be environment-specific and evolve quickly. Treat those detectors as best-effort safeguards rather than exhaustive secret scanning, and use dedicated secret-scanning tooling if you need stronger guarantees.

## Security Notes

- Whitelist patterns are compiled case-insensitively.
- Custom patterns must stay within basic length and complexity limits and are meant for trusted admin-authored configuration.
- Very large strings and oversized nested collections are rejected instead of being scanned indefinitely.

## Masking Notes

- `HASH` masking emits the first 16 hexadecimal characters of the SHA-256 digest, for example `[HASH:8f434346648f6b96]`.
- Earlier releases emitted 8 hexadecimal characters. Update downstream parsers if they assumed the shorter fixed-width placeholder.

## Testing

```bash
# Rust unit tests
make test

# Python tests
make test-python

# Benchmarks
make bench
```

## Performance

Expected 5-10x speedup over Python implementation for typical payloads.
