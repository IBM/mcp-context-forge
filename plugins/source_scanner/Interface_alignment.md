# Source Scanner – Interface Alignment Checklist

This document defines the agreed interfaces and responsibilities between components in the Source Scanner plugin, to avoid implementation mismatch and duplicated logic.

All contributors should align with the following rules before implementing their components.

---

## 1. Finding schema & severity

- `Finding.severity` **must be one of**:
  - `"ERROR"`
  - `"WARNING"`
  - `"INFO"`
- Scanner runners (Semgrep / Bandit) **must not introduce new severity levels**
- Severity normalization and ordering are handled centrally (Normalizer / Policy), **not inside individual scanners**

---

## 2. Deduplication responsibility

- **Scanners do NOT perform deduplication**
- Each scanner returns a raw `List[Finding]`
- Merging and deduplication across scanners is handled by:

```python
ParserNormalizer.merge_dedup(...)
```

- Deduplication relies on a stable key (e.g. `Finding.dedup_key()` or equivalent canonical fields)

---

## 3. Policy evaluation (single entry point)

All block / allow decisions go through:

```python
PolicyChecker.evaluate(
    findings: List[Finding],
    threshold: str,
    fail_on_critical: bool,
)
```

- Scanners and normalizers **must not enforce policy decisions**
- Policy logic is centralized and configurable

---

## 4. Configuration shape

`SourceScannerConfig` supports both configuration styles.

### Top-level config

```yaml
semgrep:
  enabled: true
bandit:
  enabled: true
```

### Nested config

```yaml
scanners:
  semgrep:
    enabled: true
  bandit:
    enabled: true
```

- Config merging / normalization is handled inside `SourceScannerConfig`
- Downstream components should assume a **normalized config object**

---

## 5. Subprocess execution utility

All external commands **must** use:

```python
utils.exec.run_command(...)
```

`run_command` behavior:
- Returns `ExecResult`
- **Does not raise on timeout**
- Sets `ExecResult.timed_out = True` instead

Callers decide how to map timeouts or failures into domain-specific errors.

---

## 6. Scan failure behavior (important)

- Current hook implementation is **fail-open**
- Behavior for **enforce mode + scan failure** (e.g. clone error, scanner binary missing) is:
  - Explicitly configurable
  - Documented in `design.md`
  - Final enforcement behavior may be implemented later

---

If any component behavior is unclear, please check `design.md` or align with the Technical Lead before implementation.