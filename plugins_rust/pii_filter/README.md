# PII Filter (Rust)

Rust-backed PII detection and masking for ContextForge.

This directory is the primary documentation for the Rust PII plugin. The
canonical supported runtime configuration lives in
[`plugins/config.yaml`](../../plugins/config.yaml), and the Rust parser in
[`src/config.rs`](./src/config.rs) is expected to match that contract.
The Python adapter is intentionally thin and passes the plugin config through
to Rust unchanged instead of mirroring the schema in Python.

The plugin package metadata that the plugin loader can inspect lives in
[`plugins/pii_filter_rust/plugin-manifest.yaml`](../../plugins/pii_filter_rust/plugin-manifest.yaml).

## What This Plugin Supports

The Rust plugin currently supports these detector flags:

- `detect_ssn`
- `detect_bsn`
- `detect_credit_card`
- `detect_email`
- `detect_phone`
- `detect_ip_address`
- `detect_date_of_birth`
- `detect_passport`
- `detect_driver_license`
- `detect_bank_account`
- `detect_medical_record`
- `detect_full_name`
- `detect_street_address`
- `detect_us_aba_routing_number`
- `detect_us_zip_code`
- `detect_us_ein`
- `detect_us_itin`

It also supports:

- `default_mask_strategy`
- `redaction_text`
- `block_on_detection`
- `log_detections`
- `include_detection_details`
- `custom_patterns`
- `whitelist_patterns`

Supported masking strategy values are:

- `auto` (alias: `default`)
- `redact`
- `partial`
- `hash`
- `tokenize`
- `remove`

`custom_patterns` entries must provide:

- `pattern`
- `description`
- `mask_strategy`

The Rust plugin provides an expanded feature set compared to the Python-only
PII detector. Note that if a key is not present in `plugins/config.yaml` for
`RustPIIFilterPlugin`, it is not part of the Rust plugin contract.

Driver license scope is intentionally narrow:

- U.S. only
- Top 4 states by population only: California, Texas, Florida, and New York
- Requires both a driver-license label and an explicit state reference

Passport scope is intentionally limited and guaranteed only for these formats:

- U.S. format: `9 digits`
- EU-style format: `2 uppercase letters + 7 digits`
- Requires either a passport label such as `passport no` / `passport number` or a U.S. / EU region marker
- Not a worldwide passport validator beyond those documented formats

Additional detector scope notes:

- `detect_phone` is validated with `rlibphonenumber` and is guaranteed for U.S.
  domestic formats plus international numbers that include a country code. It
  is not a comprehensive parser for unlabeled local formats in every region.
- `detect_ip_address` is guaranteed for IPv4 and standard fully expanded or
  compressed IPv6 forms such as `2001:db8::1`.
- `detect_date_of_birth` is contextual and requires a DOB or birth-date style
  label.
- `detect_bank_account` is guaranteed for contextual numeric account identifiers
  (`8-17 digits`) and checksum-validated IBAN. It is not a general global
  bank-account validator beyond those formats.
- `detect_medical_record` is contextual and limited to `MRN` / `Medical Record`
  labeled identifiers.
- `detect_full_name` is contextual and limited to labeled full-name fields.
- `detect_street_address` is contextual and limited to labeled addresses using
  common English street suffixes such as `street`, `st`, `avenue`, `ave`, or
  `road`.

## Detection Contract

The table below is the intended contract for what the Rust detector does and
does not guarantee today.

| Detector | Guaranteed coverage | Explicitly not guaranteed |
| --- | --- | --- |
| `detect_ssn` | U.S. SSN shape with invalid ranges rejected (`000`, `666`, `9xx`, `00`, `0000`) | General 9-digit identifiers outside the SSN rules |
| `detect_bsn` | Dutch BSN with explicit BSN context and elfproef validation | Unlabeled 9-digit numbers |
| `detect_credit_card` | Card numbers that pass Luhn | Arbitrary 12-19 digit numbers that fail Luhn |
| `detect_email` | Standard email address syntax | Mailbox deliverability or ownership |
| `detect_phone` | `rlibphonenumber`-validated U.S. domestic formats and international numbers with country code | Every local/national format worldwide without country context |
| `detect_ip_address` | IPv4 and standard fully expanded or compressed IPv6 | IPv4-mapped IPv6 or every possible exotic textual variant |
| `detect_date_of_birth` | DOB or birth-date labeled dates | Unlabeled dates in free text |
| `detect_passport` | U.S. `9 digits` and EU-style `2 letters + 7 digits` with passport label or `US` / `EU` region marker | Other passport formats or worldwide passport validation |
| `detect_driver_license` | CA, TX, FL, and NY only, with driver-license label or state marker | Other U.S. states, non-U.S. licenses, or a global license detector |
| `detect_bank_account` | Contextual `8-17 digit` account numbers and checksum-valid IBAN | Unlabeled U.S. account numbers or arbitrary country-specific account schemes |
| `detect_medical_record` | `MRN` / `Medical Record` labeled identifiers | Unlabeled hospital or patient identifiers |
| `detect_full_name` | Labeled full-name fields | Unlabeled person-name recognition in free text |
| `detect_street_address` | Labeled addresses with common English street suffixes | Unlabeled addresses or full global address parsing |
| `detect_us_aba_routing_number` | 9-digit U.S. ABA routing transit numbers that satisfy prefix and checksum rules | A guarantee that the number is currently assigned or active at a bank |
| `detect_us_zip_code` | Labeled U.S. ZIP / ZIP+4 | Unlabeled 5-digit or 9-digit numbers |
| `detect_us_ein` | Labeled U.S. EIN | Unlabeled 9-digit tax identifiers |
| `detect_us_itin` | Labeled U.S. ITIN within supported issuance ranges | Unlabeled 9-digit tax identifiers or non-ITIN formats |

## Default Shipped Behavior

The shipped plugin entry in [`plugins/config.yaml`](../../plugins/config.yaml)
is the dedicated Rust wrapper:

- Plugin class: `plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin`
- Mode: `disabled`
- Hooks: `prompt_pre_fetch`, `prompt_post_fetch`, `tool_pre_invoke`, `tool_post_invoke`
- Masking: `partial`
- Blocking on detection: `false`

Rust-only detector flags such as `detect_full_name`, `detect_street_address`,
`detect_us_aba_routing_number`, `detect_us_zip_code`, `detect_us_ein`, and
`detect_us_itin` are part of this plugin contract.

Important behavior notes:

- `mode: enforce` means plugin violations are enforced when the plugin returns a
  violation.
- `block_on_detection: true` makes the plugin fail closed on detections.
- `block_on_detection: false` masks detected PII and continues processing.
- If the Rust extension module is not installed, `RustPIIFilterPlugin`
  fails fast instead of silently falling back to the Python detector.

## Logging and Safety

The Rust path is designed to log metadata only.

Logged fields are limited to safe values such as:

- operation or hook name
- path kind or path label
- detection count
- detected PII type names
- `block_on_detection`

The Rust plugin should not log:

- raw prompt content
- raw tool arguments or tool results
- matched sensitive values

## Build and Install

Prerequisites:

- Rust toolchain with edition 2024 support
- Python 3.11+
- `uv`
- `maturin`

Common commands:

```bash
cd plugins_rust/pii_filter

# Build/install the extension into the active environment
make install

# Or build directly
maturin develop --release
```

Published package and import names:

- package: `mcpgateway-pii-filter`
- extension module: `pii_filter_rust`
- detector import: `from pii_filter_rust import PIIDetectorRust`
- plugin wrapper import: `from plugins.pii_filter_rust.pii_filter_rust import RustPIIFilterPlugin`

## Testing

Rust crate tests:

```bash
cargo test --manifest-path Cargo.toml --tests
```

Python unit tests for the Python plugin:

```bash
uv run pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py
```

Python unit tests for the Rust plugin:

```bash
uv run pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter_rust.py
```

## Benchmarks and Follow-up Validation

Local benchmark entrypoints:

```bash
# Criterion benchmarks
cargo bench

# Python vs Rust comparison helper
python benchmarks/compare_pii_filter.py
```

Current benchmark scripts exist, but end-to-end and Locust validation are
intentionally tracked as follow-up work and are not documented here as complete.

## Limitations and Non-goals

- The Rust plugin offers expanded capabilities beyond the Python plugin, rather than being strictly equivalent.
- Only the config keys present in `plugins/config.yaml` are supported.
- End-to-end and Locust coverage are not part of this directory’s current
  completion criteria.
- Secrets-detection responsibilities should remain with the dedicated secrets
  detection plugin rather than being inferred from the Rust PII plugin.
- `detect_driver_license` is not a generic global license detector. It is
  currently limited to U.S. formats for CA, TX, FL, and NY, using either a
  driver-license label or a state marker.
- `detect_passport` is guaranteed only for U.S. `9 digits` and EU-style
  `2 letters + 7 digits` formats, using either a passport label or a U.S. / EU
  region marker.
- `detect_phone` is not a general global phone parser; it uses
  `rlibphonenumber` to validate U.S. domestic formats and international numbers
  with country code.
- `detect_ip_address` is guaranteed for IPv4 and standard fully expanded or
  compressed IPv6 forms.
- `detect_date_of_birth`, `detect_medical_record`, `detect_full_name`, and
  `detect_street_address` are contextual detectors rather than free-form global
  parsers.
- `detect_bank_account` is guaranteed for contextual `8-17 digit` account
  numbers and checksum-validated IBAN, not arbitrary country-specific account
  schemes.
- `detect_us_aba_routing_number` validates only ABA prefix and checksum rules.
  It does not confirm that a routing number is currently assigned to a live
  financial institution.
