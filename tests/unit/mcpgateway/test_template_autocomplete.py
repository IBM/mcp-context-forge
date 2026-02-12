# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_template_autocomplete.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests ensuring all password inputs in HTML templates have correct
autocomplete attributes to prevent browser autofill on sensitive fields.
"""

# Standard
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "mcpgateway" / "templates"

# Expected autocomplete values for specific fields by (template_basename, field_id_or_name).
# Any password field not listed here must have autocomplete="off".
EXPECTED_AUTOCOMPLETE: Dict[Tuple[str, str], str] = {
    # login.html – real user credential fields
    ("login.html", "password"): "current-password",
    # change-password-required.html – password rotation
    ("change-password-required.html", "current_password"): "current-password",
    ("change-password-required.html", "new_password"): "new-password",
    ("change-password-required.html", "confirm_password"): "new-password",
    # admin.html – create-user form
    ("admin.html", "new_user_password"): "new-password",
}


class _PasswordInputCollector(HTMLParser):
    """Collect <input type="password"> elements outside HTML comments."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: List[Dict[str, Optional[str]]] = []
        self._in_comment = False

    def handle_comment(self, data: str) -> None:
        # We don't collect anything from commented-out markup.
        pass

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "input":
            return
        attr_dict = {k: v for k, v in attrs}
        if attr_dict.get("type", "").lower() != "password":
            return
        self.fields.append(attr_dict)


def _strip_html_comments(html: str) -> str:
    """Remove HTML comment blocks so commented-out inputs are ignored."""
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def _collect_password_fields(template_path: Path) -> List[Dict[str, Optional[str]]]:
    """Parse a template and return active (non-commented) password input attrs."""
    raw = template_path.read_text(encoding="utf-8")
    clean = _strip_html_comments(raw)
    parser = _PasswordInputCollector()
    parser.feed(clean)
    return parser.fields


class TestPasswordAutocompleteAttributes:
    """Every <input type='password'> must declare an autocomplete attribute."""

    def test_all_password_fields_have_autocomplete(self) -> None:
        """No active password input should be missing the autocomplete attr."""
        missing: List[str] = []
        for tpl in sorted(TEMPLATES_DIR.glob("**/*.html")):
            for field in _collect_password_fields(tpl):
                if "autocomplete" not in field:
                    ident = field.get("id") or field.get("name") or "(anonymous)"
                    missing.append(f"{tpl.name}#{ident}")

        assert not missing, (
            "Password fields without autocomplete attribute:\n  "
            + "\n  ".join(missing)
        )

    def test_expected_autocomplete_values(self) -> None:
        """Fields with known semantic roles must use the correct value."""
        wrong: List[str] = []
        for (tpl_name, field_key), expected in EXPECTED_AUTOCOMPLETE.items():
            tpl_path = TEMPLATES_DIR / tpl_name
            if not tpl_path.exists():
                wrong.append(f"{tpl_name} not found")
                continue
            for field in _collect_password_fields(tpl_path):
                fid = field.get("id") or field.get("name")
                if fid == field_key:
                    actual = field.get("autocomplete")
                    if actual != expected:
                        wrong.append(
                            f"{tpl_name}#{field_key}: expected '{expected}', got '{actual}'"
                        )
                    break
            else:
                wrong.append(f"{tpl_name}#{field_key}: field not found")

        assert not wrong, (
            "Incorrect autocomplete values:\n  " + "\n  ".join(wrong)
        )

    def test_api_key_and_secret_fields_use_off(self) -> None:
        """All password fields NOT in the expected-override map must use 'off'."""
        override_keys = set(EXPECTED_AUTOCOMPLETE.keys())
        not_off: List[str] = []

        for tpl in sorted(TEMPLATES_DIR.glob("**/*.html")):
            for field in _collect_password_fields(tpl):
                fid = field.get("id") or field.get("name")
                if (tpl.name, fid) in override_keys:
                    continue  # checked elsewhere
                actual = field.get("autocomplete")
                if actual != "off":
                    not_off.append(
                        f"{tpl.name}#{fid}: expected 'off', got '{actual}'"
                    )

        assert not not_off, (
            "Non-credential password fields must have autocomplete='off':\n  "
            + "\n  ".join(not_off)
        )

    def test_login_template_preserves_credential_autocomplete(self) -> None:
        """login.html password field must keep autocomplete='current-password'."""
        tpl_path = TEMPLATES_DIR / "login.html"
        fields = _collect_password_fields(tpl_path)
        assert len(fields) >= 1, "login.html should have at least 1 password field"
        pw_field = fields[0]
        assert pw_field.get("autocomplete") == "current-password", (
            f"login.html password should be 'current-password', "
            f"got '{pw_field.get('autocomplete')}'"
        )

    def test_change_password_template_has_correct_values(self) -> None:
        """change-password-required.html must use current-password and new-password."""
        tpl_path = TEMPLATES_DIR / "change-password-required.html"
        fields = _collect_password_fields(tpl_path)
        assert len(fields) == 3, (
            f"Expected 3 password fields in change-password-required.html, got {len(fields)}"
        )
        values = [f.get("autocomplete") for f in fields]
        assert values == ["current-password", "new-password", "new-password"], (
            f"Unexpected autocomplete values: {values}"
        )

    def test_commented_out_fields_are_future_proofed(self) -> None:
        """Commented-out password fields should also have autocomplete for when they are enabled."""
        tpl_path = TEMPLATES_DIR / "admin.html"
        raw = tpl_path.read_text(encoding="utf-8")

        # Extract HTML comment blocks
        comments = re.findall(r"<!--(.*?)-->", raw, flags=re.DOTALL)
        comment_html = "\n".join(comments)

        # Parse password inputs inside comments
        parser = _PasswordInputCollector()
        parser.feed(comment_html)

        missing: List[str] = []
        for field in parser.fields:
            if "autocomplete" not in field:
                ident = field.get("id") or field.get("name") or "(anonymous)"
                missing.append(f"admin.html (commented)#{ident}")

        assert not missing, (
            "Commented-out password fields without autocomplete attribute:\n  "
            + "\n  ".join(missing)
        )
