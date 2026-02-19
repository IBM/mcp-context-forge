# Rust Plugin Import Path Migration (v1.0.0-RC1)

## Breaking Change

The PII filter Rust module import path has changed:

```python
# ❌ OLD (Pre-RC1)
from plugins_rust import PIIDetectorRust

# ✅ NEW (RC1+)
from pii_filter_rust.pii_filter_rust import PIIDetectorRust
```

**Note**: The double-nested import path (`pii_filter_rust.pii_filter_rust`) is correct:
- First `pii_filter_rust` = package name (from `Cargo.toml` `[lib] name`)
- Second `pii_filter_rust` = module name (from `#[pymodule]` in `lib.rs`)
- `PIIDetectorRust` = class exported via `m.add_class::<PIIDetectorRust>()`

## Why?

- **Consistency**: Module name matches Cargo.toml `[lib]` name with _rust suffix
- **Clarity**: Each plugin has distinct module name
- **PyPI**: Aligns with package name `mcpgateway-pii-filter`
- **Windows Compatibility**: Removed problematic `include` directives that caused `.pyd` file conflicts

## Who's Affected?

- ✅ External code importing `PIIDetectorRust` directly
- ✅ Custom plugins using Rust PII detector
- ❌ Standard plugin usage (Python wrapper handles this)
- ❌ MCP Gateway core (already updated)

## Migration

### 1. Find Affected Code

```bash
grep -r "from plugins_rust import" . --include="*.py"
```

### 2. Update Imports

```python
# Before
from plugins_rust import PIIDetectorRust

# After
from pii_filter_rust.pii_filter_rust import PIIDetectorRust
```

### 3. Reinstall Plugin

```bash
cd plugins_rust/pii_filter
make install
```

### 4. Verify

```bash
python -c "from pii_filter_rust.pii_filter_rust import PIIDetectorRust; print('✓ OK')"
```

## Common Scenarios

### Direct Rust Usage

```python
# Update import only
try:
    from pii_filter_rust.pii_filter_rust import PIIDetectorRust  # Changed
    detector = PIIDetectorRust(config)
except ImportError:
    from plugins.pii_filter.pii_filter import PIIDetector
    detector = PIIDetector(config)
```

### Python Wrapper (Recommended)

**No changes needed** - wrapper already updated:

```python
from plugins.pii_filter.pii_filter import RustPIIDetector
detector = RustPIIDetector(config)
```

### Plugin Config

**No changes needed** - config unchanged:

```yaml
plugins:
  - name: "PII Filter"
    kind: "plugins.pii_filter.pii_filter.PIIFilter"
```

## Troubleshooting

### `ImportError: No module named 'pii_filter_rust'`

```bash
cd plugins_rust/pii_filter
make clean
make install
python -c "from pii_filter_rust.pii_filter_rust import PIIDetectorRust; print('OK')"
```

### `ImportError: No module named 'plugins_rust'`

Update imports to use `pii_filter_rust` (see step 2 above).

### Falls Back to Python

Check logs for import errors, verify installation:

```bash
pip list | grep mcpgateway-pii-filter
```

## Future Plugins

All Rust plugins follow this pattern:

All Rust plugins now use consistent naming with `_rust` suffix and double-nested imports:
- `from pii_filter_rust.pii_filter_rust import PIIDetectorRust`
- `from secrets_detection_rust.secrets_detection_rust import py_scan_container`
- `from encoded_exfil_detection_rust.encoded_exfil_detection_rust import py_scan_container`

The double-nested path is required because PyO3 creates a package structure where the module name (from `#[pymodule]`) is nested inside the package name (from `Cargo.toml` `[lib] name`).

## Resources

- [Rust Plugins Docs](../../docs/docs/using/plugins/rust-plugins.md)
- [PII Filter README](pii_filter/README.md)
- [Changelog](../../CHANGELOG.md)

---

**Difficulty**: Low
**Time**: 5-15 minutes
**Backward Compatible**: No
