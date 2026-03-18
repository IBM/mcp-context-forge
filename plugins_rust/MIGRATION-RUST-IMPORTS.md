# Rust Plugin Import Path Migration (v1.0.0-RC1)

## Breaking Change

The PII filter Rust module import path has changed:

```python
# ❌ OLD (Pre-RC1)
from plugins_rust import PIIDetectorRust

# ✅ NEW (RC1+)
from pii_filter_rust import PIIDetectorRust
```

**Note**: Public documentation and verification commands should use the top-level
package import `pii_filter_rust`. The plugin wrapper path is separate:

```python
from plugins.pii_filter_rust.pii_filter_rust import RustPIIFilterPlugin
```

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
from pii_filter_rust import PIIDetectorRust
```

### 3. Reinstall Plugin

```bash
cd plugins_rust/pii_filter
make install
```

### 4. Verify

```bash
python -c "from pii_filter_rust import PIIDetectorRust; print('✓ OK')"
```

## Common Scenarios

### Direct Rust Usage

```python
# Update import only
try:
    from pii_filter_rust import PIIDetectorRust  # Changed
    detector = PIIDetectorRust(config)
except ImportError:
    from plugins.pii_filter.pii_filter import PIIDetector
    detector = PIIDetector(config)
```

### Python Wrapper (Recommended)

The dedicated Rust plugin wrapper now lives at:

```python
from plugins.pii_filter_rust.pii_filter_rust import RustPIIFilterPlugin
```

### Plugin Config

If you are enabling the dedicated Rust plugin, the shipped config now points at
the dedicated wrapper:

```yaml
plugins:
  - name: "RustPIIFilterPlugin"
    kind: "plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin"
```

## Troubleshooting

### `ImportError: No module named 'pii_filter_rust'`

```bash
cd plugins_rust/pii_filter
make clean
make install
python -c "from pii_filter_rust import PIIDetectorRust; print('OK')"
```

### `ImportError: No module named 'plugins_rust'`

Update imports to use `pii_filter_rust` (see step 2 above).

### Falls Back to Python

Check logs for import errors, verify installation:

```bash
pip list | grep mcpgateway-pii-filter
```

## Future Plugins

Rust plugins now use consistent `_rust` naming. Current examples:
- `from pii_filter_rust import PIIDetectorRust`
- `from secrets_detection_rust.secrets_detection_rust import py_scan_container`
- `from encoded_exfil_detection_rust.encoded_exfil_detection_rust import py_scan_container`

## Resources

- [Rust Plugins Docs](../../docs/docs/using/plugins/rust-plugins.md)
- [PII Filter README](pii_filter/README.md)
- [Changelog](../../CHANGELOG.md)

---

**Difficulty**: Low
**Time**: 5-15 minutes
**Backward Compatible**: No
