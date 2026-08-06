# Support Bundle Secret Redaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Admin UI support bundle from writing the application's JWT signing secret (and the identity-claims signing secret) into `settings.json` in clear text.

**Architecture:** Replace the hand-maintained `exclude_fields` allowlist in `SupportBundleService._collect_settings()` with a *computed* exclusion set derived from the `Settings` model itself — every `SecretStr`-annotated field, plus every string-annotated field whose name matches a narrow secret-name regex. Then remove the root cause by retyping the two plain-`str` secret fields (`csrf_secret_key`, `identity_claims_secret`) as `SecretStr`, so they cannot leak through any future print/log/dump path. A meta-test walks `Settings.model_fields` and fails CI if a future secret field is not covered.

**Tech Stack:** Python 3.11+, Pydantic v2 / pydantic-settings, orjson, pytest, FastAPI.

## Background — verified facts

Confirmed by direct inspection of this worktree; do not re-derive.

1. `mcpgateway/config.py:408` — `csrf_secret_key: str` is a plain `str`, not `SecretStr`.
2. `mcpgateway/config.py:1594-1595` — when `CSRF_SECRET_KEY` is unset (the shipped default) the validator copies the JWT signing secret into it verbatim.
3. `mcpgateway/services/support_bundle_service.py:288-301` — `_collect_settings()` drops a hand-maintained 12-name `exclude_fields` set that does not contain `csrf_secret_key`, then `generate_bundle()` (line 440) writes it with `orjson.dumps(app_settings, default=str, ...)`.
4. **Why only this field leaks:** every other secret in `Settings` is typed `SecretStr`, and under `default=str` orjson renders `SecretStr('hunter2')` as `"**********"`. Verified: `orjson.dumps({'a': SecretStr('hunter2')}, default=str)` → `b'{"a":"**********"}'`. The `SecretStr` type has been doing the real redaction; plain-`str` secrets are the hole.
5. **Second leak, not in the issue report:** a sweep of all 768 `Settings` fields found exactly two secret-bearing plain-`str` fields — `csrf_secret_key` and `identity_claims_secret` (`config.py:683`, used at `mcpgateway/utils/identity_propagation.py:63`, and itself falling back to the JWT secret). Same blast radius. Both are fixed here.
6. **`environment.json` is not affected.** `_collect_env_config()` routes through `_is_secret()`, which matches `SECRET`/`TOKEN`/`PASS`/`KEY` substrings, so `CSRF_SECRET_KEY` is already masked there. The leak is confined to `settings.json`.
7. **The issue's suggested regex is too broad.** `*secret*|*password*|*token*|*key*` matches 88 of 768 fields, ~60 of them harmless `int`/`bool` knobs (`token_expiry`, `password_min_length`, `csrf_token_name`, `password_policy_enabled`, …). Redacting those would gut the bundle's debugging value and the "allow-listed as safe" list would be larger than the list being replaced. This plan uses a narrow regex (`secret|password|passwd|credential|passphrase|private_key|api_key`) combined with a string-type filter, which selects exactly `csrf_secret_key`, `identity_claims_secret`, and `jwt_private_key_path` — the last being a filesystem path, handled by a one-entry safe list.
8. Field-annotation census with the narrow regex: 20 `SecretStr` fields, 49 name matches, of which the only `str`-annotated ones are the three named in point 7.
9. `Settings.model_config` does **not** set `validate_assignment`. Assigning a raw `str` to a `SecretStr` field will **not** be coerced — it must be wrapped explicitly.
10. `build/lib/**` contains a stale copy of these modules. It is a build artifact. **Do not edit anything under `build/`.**

## Prototype verification

The design in Tasks 1-2 was executed as a throwaway prototype against this worktree before the plan was written. Results — treat these as the expected outcome when implementing, and investigate any divergence rather than adjusting the assertions:

- `_is_string_annotation`: `str` → True, `Optional[str]` → True, `Dict[str, str]` → False, `int` → False, `Optional[int]` → False.
- `_secret_field_names()` returns **22** names: the 20 `SecretStr` fields plus exactly `csrf_secret_key` and `identity_claims_secret`. No `SecretStr` field is missed.
- `jwt_private_key_path` **does** match `_SECRET_NAME_RE` (via the `private_key` alternative) and **is** string-typed, so `_SAFE_STRING_FIELDS` is load-bearing — dropping it over-redacts a filesystem path.
- None of `token_expiry`, `password_min_length`, `password_policy_enabled`, `min_secret_length`, `require_strong_secrets`, `csrf_token_name`, `host`, `port` is selected.
- `settings.model_dump(exclude=<the 22-name set>)` succeeds and emits 708 keys, with `csrf_secret_key` absent and `host` present.
- The sentinel `"sentinel-jwt-canary-DO-NOT-USE-IN-PRODUCTION-0123456789"` passes the `Settings` security validators, and the CSRF fallback copies it into `csrf_secret_key` as expected.
- End-to-end: with **current** `main` code the sentinel appears in `settings.json` of the generated zip (reproduction confirmed). With the Task 2 body patched in, the sentinel appears in **no** bundle member. Members produced with `include_logs=False`: `MANIFEST.json`, `version.json`, `system_info.json`, `settings.json`, `environment.json`, `README.md`.

## Global Constraints

- Python >= 3.11, type hints required; formatting is Ruff with line length 200.
- Every new function and method needs a docstring (`interrogate` gate) with `Args:` / `Returns:` sections, matching the style already in `support_bundle_service.py`.
- Commits must be signed off: `git commit -s` (DCO). Use Conventional Commits (`fix:`, `test:`, `docs:`).
- Never mention AI assistants in commits, PRs, or diffs.
- Test files that contain literal fake secrets need `# pragma: allowlist secret` on the line, or `make detect-secrets-scan` fails.
- Do not modify anything under `build/`.
- Import grouping follows the existing isort sections in each file: `# Standard`, `# Third-Party`, `# First-Party`.

## Disclosure gate (do before Task 1)

This tracks internal issue `contextforge-org/internal_issues#522`, reported upstream through IBM PSIRT rather than the public tracker. **Before pushing any branch or opening any PR, confirm the embargo state with the PSIRT contact.** If still embargoed, keep the work local and keep commit messages factual and non-weaponised (describe the fix, not the exploitation path).

Operator-facing consequence for the release note: any support bundle generated by an affected deployment before this fix must be treated as a disclosure of the JWT signing secret. Remediation is rotating `JWT_SECRET_KEY`, which invalidates all outstanding tokens.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `mcpgateway/services/support_bundle_service.py` | Add module-level `_SECRET_NAME_RE` / `_SAFE_STRING_FIELDS` / `REDACTED_MARKER` and the `_secret_field_names()` classmethod; rewire `_collect_settings()` to use it. | 1, 2 |
| `tests/unit/mcpgateway/services/test_support_bundle_service.py` | Unit tests for the detection helper; end-to-end sentinel scan of the generated zip; meta-test over `Settings.model_fields`; anti-over-redaction test. | 1, 2 |
| `mcpgateway/config.py` | Retype `csrf_secret_key` and `identity_claims_secret` to `SecretStr`; fix the fallback guards. | 3, 4 |
| `mcpgateway/services/csrf_service.py`, `mcpgateway/routers/auth.py`, `mcpgateway/routers/email_auth.py` | Unwrap `csrf_secret_key` with `.get_secret_value()`. | 3 |
| `mcpgateway/utils/identity_propagation.py` | Unwrap `identity_claims_secret` with `.get_secret_value()`. | 4 |
| `tests/unit/mcpgateway/middleware/test_csrf_fixes.py`, `tests/unit/mcpgateway/services/test_csrf_service.py`, `tests/unit/mcpgateway/routers/test_auth.py`, `tests/unit/mcpgateway/routers/test_email_auth_router.py` | Mock assignments become `SecretStr`. | 3 |
| `tests/unit/mcpgateway/test_identity_propagation.py` | Mock assignments become `SecretStr`. | 4 |
| `.env.example`, `mcpgateway/config.py` field description, `mcpgateway/templates/` Admin UI copy | Document the CSRF/JWT key reuse and correct the redaction claim. | 5 |

Task 1 and 2 together fix the vulnerability and are mergeable on their own. Tasks 3 and 4 are the durable root-cause fix and can each be reviewed and rejected independently. Task 5 is documentation.

---

### Task 1: Computed secret-field detection

**Files:**
- Modify: `mcpgateway/services/support_bundle_service.py` (add constants after the imports, add `_secret_field_names()` classmethod near `_is_secret`, around line 108)
- Test: `tests/unit/mcpgateway/services/test_support_bundle_service.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SupportBundleService._secret_field_names() -> set[str]` — classmethod, no arguments, returns the set of `Settings` field names that must never appear in `settings.json`.
  - Module constants `_SECRET_NAME_RE: re.Pattern[str]`, `_SAFE_STRING_FIELDS: frozenset[str]`.
  - `SupportBundleService._is_string_annotation(annotation: Any) -> bool` — staticmethod.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/mcpgateway/services/test_support_bundle_service.py`, inside `class TestSupportBundleService`:

```python
    def test_secret_field_names_includes_plain_string_secrets(self):
        """Plain-str secret settings are detected, not just SecretStr ones."""
        names = SupportBundleService._secret_field_names()

        # The reported vulnerability: csrf_secret_key is a plain str that
        # defaults to a copy of the JWT signing secret.
        assert "csrf_secret_key" in names
        # Same class of bug, found during triage of the same issue.
        assert "identity_claims_secret" in names

    def test_secret_field_names_includes_every_secretstr_field(self):
        """Every SecretStr-annotated setting is detected by type alone."""
        # First-Party
        from mcpgateway.config import Settings

        names = SupportBundleService._secret_field_names()
        for field_name, field in Settings.model_fields.items():
            annotation = field.annotation
            is_secret_type = annotation is SecretStr or SecretStr in get_args(annotation)
            if is_secret_type:
                assert field_name in names, f"SecretStr field {field_name} not detected as a secret"

    def test_secret_field_names_excludes_benign_settings(self):
        """Non-secret knobs whose names contain secret-ish words are kept."""
        names = SupportBundleService._secret_field_names()

        # int/bool knobs — redacting these would gut the bundle's usefulness
        for benign in (
            "token_expiry",
            "password_min_length",
            "password_policy_enabled",
            "min_secret_length",
            "require_strong_secrets",
            "csrf_token_name",
            "host",
            "port",
        ):
            assert benign not in names, f"{benign} must not be redacted"

        # A filesystem path, not a key
        assert "jwt_private_key_path" not in names
```

Add to the imports at the top of that test file, in the existing sections:

```python
# Standard
from typing import get_args
```

```python
# Third-Party
from pydantic import SecretStr
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/services/test_support_bundle_service.py -k secret_field_names -v
```
Expected: FAIL — `AttributeError: type object 'SupportBundleService' has no attribute '_secret_field_names'`

- [ ] **Step 3: Write minimal implementation**

In `mcpgateway/services/support_bundle_service.py`, extend the third-party and standard imports:

```python
# Standard
from types import UnionType
from typing import Any, Dict, Optional, Union, get_args, get_origin
```

```python
# Third-Party
import orjson
from pydantic import BaseModel, Field, SecretStr
```

Add module-level constants immediately after the `from mcpgateway.db import engine` import block, before `class SupportBundleConfig`:

```python
# Field names that indicate a secret when the setting is string-typed.
#
# Deliberately narrower than SupportBundleService._is_secret(): bare "token"
# and "key" match ~60 harmless settings (token_expiry, password_min_length,
# csrf_token_name, ...) and redacting those would gut the bundle's value for
# the debugging it exists to support. _is_secret() can afford to be broad
# because it inspects raw environment variables whose names are unknown;
# here the field set is known and typed.
_SECRET_NAME_RE = re.compile(r"secret|password|passwd|credential|passphrase|private_key|api_key", re.IGNORECASE)

# String settings matching _SECRET_NAME_RE that are not themselves secrets.
_SAFE_STRING_FIELDS = frozenset({"jwt_private_key_path"})
```

Add these two methods to `SupportBundleService`, directly after `_is_secret()` (which ends around line 141):

```python
    @staticmethod
    def _is_string_annotation(annotation: Any) -> bool:
        """Check whether a field annotation is ``str`` or ``Optional[str]``.

        Container annotations such as ``Dict[str, str]`` are rejected so that
        a mapping setting is never mistaken for a scalar secret.

        Args:
            annotation: The declared annotation of a Pydantic model field.

        Returns:
            bool: True if the annotation resolves to a plain or optional string.

        Examples:
            >>> from typing import Dict, Optional
            >>> SupportBundleService._is_string_annotation(str)
            True
            >>> SupportBundleService._is_string_annotation(Optional[str])
            True
            >>> SupportBundleService._is_string_annotation(Dict[str, str])
            False
            >>> SupportBundleService._is_string_annotation(int)
            False
        """
        if annotation is str:
            return True
        if get_origin(annotation) in (Union, UnionType):
            return all(arg is str or arg is type(None) for arg in get_args(annotation))
        return False

    @classmethod
    def _secret_field_names(cls) -> set[str]:
        """Compute the set of settings fields that must never reach the bundle.

        A field is a secret when either:

        1. it is annotated ``SecretStr`` or ``Optional[SecretStr]`` — the
           primary rule, so any correctly typed secret added in future is
           covered without touching this module; or
        2. it is string-typed, its name matches :data:`_SECRET_NAME_RE`, and it
           is not in :data:`_SAFE_STRING_FIELDS` — the net for plain-string
           secrets that were not typed as ``SecretStr``.

        Returns:
            set[str]: Field names to exclude from ``settings.json``.

        Examples:
            >>> names = SupportBundleService._secret_field_names()
            >>> "jwt_secret_key" in names
            True
            >>> "csrf_secret_key" in names
            True
            >>> "token_expiry" in names
            False
        """
        # First-Party
        from mcpgateway.config import Settings  # pylint: disable=import-outside-toplevel

        secret_names: set[str] = set()
        for name, field in Settings.model_fields.items():
            annotation = field.annotation
            if annotation is SecretStr or SecretStr in get_args(annotation):
                secret_names.add(name)
                continue
            if name in _SAFE_STRING_FIELDS:
                continue
            if _SECRET_NAME_RE.search(name) and cls._is_string_annotation(annotation):
                secret_names.add(name)
        return secret_names
```

The `Settings` import is function-local to avoid a second module-level import of `mcpgateway.config` (the module already imports the `settings` singleton, and importing the class at module scope adds no value).

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/services/test_support_bundle_service.py -k secret_field_names -v
.venv/bin/python3 -m pytest --doctest-modules mcpgateway/services/support_bundle_service.py -q
```
Expected: PASS for all three tests and the doctests.

- [ ] **Step 5: Commit**

```bash
git add mcpgateway/services/support_bundle_service.py tests/unit/mcpgateway/services/test_support_bundle_service.py
git commit -s -m "feat(support-bundle): compute secret settings fields from the model"
```

---

### Task 2: Exclude computed secrets from `settings.json`

**Files:**
- Modify: `mcpgateway/services/support_bundle_service.py:288-301` (body of `_collect_settings`)
- Test: `tests/unit/mcpgateway/services/test_support_bundle_service.py`

**Interfaces:**
- Consumes: `SupportBundleService._secret_field_names()` from Task 1.
- Produces: `_collect_settings()` keeps its existing signature `(self) -> Dict[str, Any]` and its existing contract that secret keys are **absent** from the returned dict (not present-and-masked). Existing tests at lines 178-186 assert absence and must keep passing.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/mcpgateway/services/test_support_bundle_service.py`, inside `class TestSupportBundleService`:

```python
    def test_collect_settings_omits_csrf_secret_key(self):
        """Regression for internal issue #522: csrf_secret_key must not ship."""
        service = SupportBundleService()
        config = service._collect_settings()

        assert "csrf_secret_key" not in config
        assert "identity_claims_secret" not in config

    def test_collect_settings_keeps_benign_fields(self):
        """The bundle stays useful: non-secret settings keep their real values."""
        service = SupportBundleService()
        config = service._collect_settings()

        for benign in ("host", "port", "token_expiry", "password_min_length", "csrf_token_name"):
            assert benign in config, f"{benign} was over-redacted"

    def test_collect_settings_omits_every_detected_secret(self):
        """Meta-test: every field _secret_field_names() flags is really gone.

        This is the guard against the original bug recurring. A future secret
        setting that is neither SecretStr-typed nor name-matched will be caught
        by test_no_secret_leaks_into_bundle below; one that is detected but
        somehow still emitted is caught here.
        """
        service = SupportBundleService()
        config = service._collect_settings()

        for name in SupportBundleService._secret_field_names():
            assert name not in config, f"secret field {name} leaked into settings.json"

    def test_no_secret_leaks_into_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """End-to-end: a sentinel JWT secret appears in no bundle member.

        Byte-level rather than key-level, so the check still fires if the value
        surfaces under a different key (which is exactly how issue #522
        happened: the JWT secret leaked under the name csrf_secret_key).
        """
        # First-Party
        from mcpgateway.config import Settings

        sentinel = "sentinel-jwt-canary-DO-NOT-USE-IN-PRODUCTION-0123456789"  # pragma: allowlist secret
        sentinel_settings = Settings(
            jwt_secret_key=sentinel,
            database_url="sqlite:///:memory:",
            environment="development",
        )
        # Sanity: the fallback under test really did copy the JWT secret across.
        assert sentinel_settings.csrf_secret_key == sentinel or sentinel_settings.csrf_secret_key.get_secret_value() == sentinel

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings", sentinel_settings)

        service = SupportBundleService()
        bundle_path = service.generate_bundle(SupportBundleConfig(output_dir=tmp_path, include_logs=False))

        with zipfile.ZipFile(bundle_path) as zf:
            for member in zf.namelist():
                assert sentinel.encode() not in zf.read(member), f"JWT secret leaked into {member}"
```

The `csrf_secret_key` sanity assertion accepts both the plain-`str` and the `SecretStr` form on purpose, so this test survives Task 3 unchanged.

If `Settings(...)` rejects the sentinel (the validator enforces a 32-char minimum and rejects known-weak values), mirror the shape of `_TEST_JWT_SECRET` in `tests/conftest.py:82`, which is known to pass.

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/services/test_support_bundle_service.py -k "csrf_secret_key or detected_secret or no_secret_leaks or benign_fields" -v
```
Expected: FAIL — `test_collect_settings_omits_csrf_secret_key` asserts `"csrf_secret_key" not in config` and the key is present; `test_no_secret_leaks_into_bundle` finds the sentinel in `settings.json`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `_collect_settings()` in `mcpgateway/services/support_bundle_service.py` (the `exclude_fields` set at lines 288-300 and the `model_dump` call at 301) with:

```python
        # Exclusions are computed from the Settings model rather than
        # hand-maintained: a hardcoded list silently goes stale as new settings
        # are added, which is how the JWT signing secret shipped in support
        # bundles under the name csrf_secret_key (internal issue #522).
        config = settings.model_dump(exclude=self._secret_field_names())
```

Leave the rest of the method — the `_sanitize_url()` calls for `database_url` and `redis_url` and the `return config` — exactly as it is. Those two carry embedded credentials inside an otherwise useful value, so they are sanitized rather than dropped.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/services/test_support_bundle_service.py -v
```
Expected: PASS, including the pre-existing `test_collect_settings`, `test_collect_settings_sanitizes_only_database_url`, and `test_collect_settings_sanitizes_only_redis_url`. The last two monkeypatch `model_dump` with a `fake_dump(*, exclude=None)` stub, which still matches the new call.

- [ ] **Step 5: Commit**

```bash
git add mcpgateway/services/support_bundle_service.py tests/unit/mcpgateway/services/test_support_bundle_service.py
git commit -s -m "fix(security): exclude plain-string secrets from support bundle settings"
```

---

### Task 3: Retype `csrf_secret_key` as `SecretStr`

**Files:**
- Modify: `mcpgateway/config.py:408` (field), `mcpgateway/config.py:1594-1595` (fallback)
- Modify: `mcpgateway/services/csrf_service.py:351`
- Modify: `mcpgateway/routers/auth.py:159`, `mcpgateway/routers/auth.py:242`
- Modify: `mcpgateway/routers/email_auth.py:304`
- Test: `tests/unit/mcpgateway/middleware/test_csrf_fixes.py`, `tests/unit/mcpgateway/services/test_csrf_service.py`, `tests/unit/mcpgateway/routers/test_auth.py`, `tests/unit/mcpgateway/routers/test_email_auth_router.py`

**Interfaces:**
- Consumes: `SupportBundleService._secret_field_names()` from Task 1 — after this task `csrf_secret_key` is caught by the *type* rule instead of the *name* rule, and Task 1's `test_secret_field_names_includes_plain_string_secrets` keeps passing either way.
- Produces: `settings.csrf_secret_key` is now `SecretStr`. Every consumer must call `.get_secret_value()` before passing it to `generate_csrf_token(...)` or `CSRFService(secret=...)`, whose signatures are unchanged and still take `str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/mcpgateway/test_config.py` (append at module level; if the file groups tests in classes, add it to the class covering security validation):

```python
def test_csrf_secret_key_is_a_secret_and_falls_back_to_jwt_secret():
    """CSRF key must be SecretStr, and must still inherit the JWT secret when unset."""
    # Third-Party
    from pydantic import SecretStr

    # First-Party
    from mcpgateway.config import Settings

    jwt_value = "config-test-jwt-canary-DO-NOT-USE-IN-PRODUCTION-0123456789"  # pragma: allowlist secret
    cfg = Settings(jwt_secret_key=jwt_value, database_url="sqlite:///:memory:", environment="development")

    assert isinstance(cfg.csrf_secret_key, SecretStr)
    # The fallback still fires: SecretStr("") is truthy, so a naive
    # `if not self.csrf_secret_key` would silently leave the key empty.
    assert cfg.csrf_secret_key.get_secret_value() == jwt_value

    explicit = "config-test-csrf-canary-DO-NOT-USE-IN-PRODUCTION-0123456789"  # pragma: allowlist secret
    cfg2 = Settings(
        jwt_secret_key=jwt_value,
        csrf_secret_key=explicit,
        database_url="sqlite:///:memory:",
        environment="development",
    )
    assert cfg2.csrf_secret_key.get_secret_value() == explicit
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/test_config.py -k csrf_secret_key_is_a_secret -v
```
Expected: FAIL — `AssertionError` on `isinstance(cfg.csrf_secret_key, SecretStr)`, because the field is still `str`.

- [ ] **Step 3: Write minimal implementation**

`mcpgateway/config.py:408` — replace:

```python
    csrf_secret_key: str = Field(default="", description="Secret key for CSRF token generation (falls back to jwt_secret_key if empty)")
```

with:

```python
    csrf_secret_key: SecretStr = Field(default=SecretStr(""), description="Secret key for CSRF token generation (falls back to jwt_secret_key if empty)")
```

`mcpgateway/config.py:1594-1595` — replace:

```python
        # CSRF secret key fallback to JWT secret key
        if not self.csrf_secret_key:
            self.csrf_secret_key = self.jwt_secret_key.get_secret_value()
```

with:

```python
        # CSRF secret key fallback to JWT secret key.
        # NOTE: SecretStr("") is truthy, so the emptiness check must go through
        # get_secret_value(); `if not self.csrf_secret_key` would never fire and
        # CSRF tokens would end up signed with an empty key. Settings does not
        # set validate_assignment, so the assigned value is not coerced and has
        # to be wrapped in SecretStr explicitly.
        if not self.csrf_secret_key.get_secret_value():
            self.csrf_secret_key = SecretStr(self.jwt_secret_key.get_secret_value())
```

`SecretStr` is already imported in `config.py` (it types `jwt_secret_key`); confirm with `grep -n "SecretStr" mcpgateway/config.py | head -3` and add it to the pydantic import if absent.

Production call sites — append `.get_secret_value()` in each:

- `mcpgateway/services/csrf_service.py:351`
  ```python
      return CSRFService(secret=app_settings.csrf_secret_key.get_secret_value(), expiry=app_settings.csrf_token_expiry)
  ```
- `mcpgateway/routers/auth.py:159` and `mcpgateway/routers/auth.py:242` — change `secret=settings.csrf_secret_key` to `secret=settings.csrf_secret_key.get_secret_value()` in both `generate_csrf_token(...)` calls.
- `mcpgateway/routers/email_auth.py:304` — same change.

- [ ] **Step 4: Update the test mocks**

These use `MagicMock`, so a bare `str` assignment now raises `AttributeError: 'str' object has no attribute 'get_secret_value'`.

Assignments — wrap the value in `SecretStr(...)`, adding `from pydantic import SecretStr` to the `# Third-Party` import block of each file:

| File | Line | Current |
|---|---|---|
| `tests/unit/mcpgateway/middleware/test_csrf_fixes.py` | 42 | `mock.csrf_secret_key = "test-secret-key"` |
| `tests/unit/mcpgateway/middleware/test_csrf_fixes.py` | 303 | `mock_settings.csrf_secret_key = "test-secret"` |
| `tests/unit/mcpgateway/services/test_csrf_service.py` | 351 | `mock_settings.csrf_secret_key = "secret"` |
| `tests/unit/mcpgateway/routers/test_auth.py` | 268, 291, 324 | `mock_settings.csrf_secret_key = "secret"` |
| `tests/unit/mcpgateway/routers/test_email_auth_router.py` | 227 | `mock_settings.csrf_secret_key = "secret"` |

Example for line 42:

```python
        mock.csrf_secret_key = SecretStr("test-secret-key")  # pragma: allowlist secret
```

Reads — `tests/unit/mcpgateway/middleware/test_csrf_fixes.py` lines **62, 95, 133, 163, 225, 254** pass the mocked setting straight into `generate_csrf_token(...)`, which still expects a `str`. Each is of the form:

```python
    csrf_token = generate_csrf_token(user_id, session_id, mock_settings.csrf_secret_key, mock_settings.csrf_token_expiry)
```

Change the third argument in all six to `mock_settings.csrf_secret_key.get_secret_value()`.

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
.venv/bin/python3 -m pytest \
  tests/unit/mcpgateway/test_config.py \
  tests/unit/mcpgateway/middleware/test_csrf_fixes.py \
  tests/unit/mcpgateway/services/test_csrf_service.py \
  tests/unit/mcpgateway/routers/test_auth.py \
  tests/unit/mcpgateway/routers/test_email_auth_router.py \
  tests/unit/mcpgateway/services/test_support_bundle_service.py -v
```
Expected: PASS. Task 2's `test_no_secret_leaks_into_bundle` still passes because its sanity assertion accepts either form.

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/config.py mcpgateway/services/csrf_service.py mcpgateway/routers/auth.py mcpgateway/routers/email_auth.py tests/unit/mcpgateway/test_config.py tests/unit/mcpgateway/middleware/test_csrf_fixes.py tests/unit/mcpgateway/services/test_csrf_service.py tests/unit/mcpgateway/routers/test_auth.py tests/unit/mcpgateway/routers/test_email_auth_router.py
git commit -s -m "fix(config): type csrf_secret_key as SecretStr"
```

---

### Task 4: Retype `identity_claims_secret` as `SecretStr`

**Files:**
- Modify: `mcpgateway/config.py:683-686`
- Modify: `mcpgateway/utils/identity_propagation.py:63`
- Test: `tests/unit/mcpgateway/test_identity_propagation.py:158`, `:493-494`, `:500`, `:507`

**Interfaces:**
- Consumes: nothing from Tasks 1-3; independent of them.
- Produces: `settings.identity_claims_secret` is now `Optional[SecretStr]`. `_sign_claims(payload: str) -> str` in `identity_propagation.py` keeps its signature.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/mcpgateway/test_identity_propagation.py`, in the class that already holds `test_uses_identity_claims_secret` (around line 493):

```python
    def test_identity_claims_secret_is_a_secret_type(self):
        """The identity-claims signing key must not be a bare string."""
        # Standard
        from typing import get_args

        # Third-Party
        from pydantic import SecretStr

        # First-Party
        from mcpgateway.config import Settings

        annotation = Settings.model_fields["identity_claims_secret"].annotation
        assert SecretStr in get_args(annotation), "identity_claims_secret must be Optional[SecretStr]"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/test_identity_propagation.py -k identity_claims_secret_is_a_secret_type -v
```
Expected: FAIL — the annotation is `Optional[str]`.

- [ ] **Step 3: Write minimal implementation**

`mcpgateway/config.py:683-686` — replace:

```python
    identity_claims_secret: Optional[str] = Field(
        default=None,
        description="Secret key for signing propagated identity claims (uses JWT_SECRET_KEY if unset)",
    )
```

with:

```python
    identity_claims_secret: Optional[SecretStr] = Field(
        default=None,
        description="Secret key for signing propagated identity claims (uses JWT_SECRET_KEY if unset)",
    )
```

`mcpgateway/utils/identity_propagation.py:63` — replace:

```python
    secret = settings.identity_claims_secret or (settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else "")
```

with:

```python
    configured = settings.identity_claims_secret.get_secret_value() if settings.identity_claims_secret else ""
    secret = configured or (settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else "")
```

- [ ] **Step 4: Update the test mocks**

Add `from pydantic import SecretStr` to the `# Third-Party` imports of `tests/unit/mcpgateway/test_identity_propagation.py`, then:

- line 158: `mock_settings.identity_claims_secret = SecretStr("test-secret")  # pragma: allowlist secret`
- line 494: `mock_settings.identity_claims_secret = SecretStr("my-secret")  # pragma: allowlist secret`
- lines 500 and 507 already assign `None`; leave them, they exercise the fallback branch.

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
.venv/bin/python3 -m pytest tests/unit/mcpgateway/test_identity_propagation.py tests/unit/mcpgateway/services/test_support_bundle_service.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/config.py mcpgateway/utils/identity_propagation.py tests/unit/mcpgateway/test_identity_propagation.py
git commit -s -m "fix(config): type identity_claims_secret as SecretStr"
```

---

### Task 5: Documentation and UI copy

**Files:**
- Modify: `.env.example:82-83` (the `CSRF_SECRET_KEY` entry)
- Modify: `mcpgateway/config.py:408` (field description)
- Modify: `mcpgateway/templates/version_info_partial.html:456-459` (support-bundle redaction claim)
- Test: manual verification plus `make check-env`

**Interfaces:**
- Consumes: the behaviour established in Tasks 2-4.
- Produces: no code interfaces.

- [ ] **Step 1: Review the Admin UI redaction claim**

The claim the issue calls unmet lives at **`mcpgateway/templates/version_info_partial.html:456-459`**. It is wrapped across source lines, so grepping the full sentence finds nothing — use `grep -n "sensitive data" mcpgateway/templates/version_info_partial.html`. Current text:

```html
        <p class="text-sm text-gray-600 dark:text-gray-400 mt-1">
          Download a comprehensive diagnostics bundle for troubleshooting. All
          sensitive data (passwords, tokens, secrets) are automatically
          redacted.
        </p>
```

After Tasks 2-4 this is true for `settings.json` and `environment.json`. It is **not** unconditionally true for `logs/` — `_collect_logs()` sanitizes log text with the regex-based `SENSITIVE_PATTERNS` (`support_bundle_service.py:94-105`), which is best-effort pattern matching over free text, not a guarantee. Narrow the copy so it does not overpromise:

```html
        <p class="text-sm text-gray-600 dark:text-gray-400 mt-1">
          Download a comprehensive diagnostics bundle for troubleshooting.
          Configuration secrets (passwords, tokens, signing keys) are omitted,
          and known credential patterns are redacted from included logs. Review
          the bundle before sharing it outside your organization.
        </p>
```

The added review prompt matters: the whole exposure path in this issue is a bundle leaving the operator's trust boundary.

- [ ] **Step 2: Document the key-reuse behaviour**

In `.env.example:82-83`, replace:

```bash
# Secret key for CSRF token generation (falls back to JWT_SECRET_KEY if empty)
CSRF_SECRET_KEY=
```

with:

```bash
# Secret used to sign CSRF tokens. If left unset, the application reuses
# JWT_SECRET_KEY for this purpose. Set it explicitly so that the two keys can
# be rotated independently.
CSRF_SECRET_KEY=
```

In `mcpgateway/config.py:408`, extend the field description:

```python
    csrf_secret_key: SecretStr = Field(default=SecretStr(""), description="Secret key for CSRF token generation. Falls back to jwt_secret_key when unset; set explicitly so the two keys can be rotated independently.")
```

- [ ] **Step 3: Verify**

Run:
```bash
make check-env
```
Expected: PASS — `.env.example` still matches the settings surface.

- [ ] **Step 4: Commit**

```bash
git add .env.example mcpgateway/config.py mcpgateway/templates/version_info_partial.html
git commit -s -m "docs: note that CSRF_SECRET_KEY reuses the JWT secret when unset"
```

---

## Final validation gate

Run from the worktree root after Task 5. Each must pass.

- [ ] `make ruff bandit interrogate pylint verify`
- [ ] `make test`
- [ ] `make coverage diff-cover`
- [ ] `make detect-secrets-scan` — the sentinel literals added in Tasks 2-4 carry `# pragma: allowlist secret`; if any still trip the scanner, audit with `make detect-secrets-audit`
- [ ] Manual end-to-end: start the gateway with `CSRF_SECRET_KEY` unset, generate a support bundle from the Admin UI Version Info tab, unzip it, and confirm `settings.json` contains neither `csrf_secret_key` nor the value of `JWT_SECRET_KEY`:
  ```bash
  unzip -p mcpgateway-support-*.zip settings.json | grep -c "$JWT_SECRET_KEY"   # expect 0
  unzip -p mcpgateway-support-*.zip settings.json | grep -c csrf_secret_key      # expect 0
  ```

## PR

Title: `fix(security): redact plain-string secrets from support bundle settings.json`

Body should cover: the `csrf_secret_key` leak and its default-config reachability; the additional `identity_claims_secret` finding surfaced during triage; the move from a hand-maintained allowlist to a model-derived exclusion set; and the operator remediation note (bundles generated before this fix are a JWT-secret disclosure; rotating `JWT_SECRET_KEY` invalidates outstanding tokens). Link the internal issue. Do not include a test plan or effort estimate.

## Deferred — not in this plan

**CSRF/JWT key separation.** The `csrf_secret_key` → `jwt_secret_key` fallback is key reuse across two purposes: a CSRF-key disclosure implies token forgery. Deriving the CSRF key via HKDF from the JWT secret instead of copying it would break that implication. It changes existing deployments' CSRF keys (invalidating in-flight CSRF tokens), so it belongs in its own PR with its own migration note. Call it out in this PR's description; do not fold it in.
