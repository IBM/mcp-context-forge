# Copyright (c) 2025, 2026 IBM Corp. and contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests that logo and icon assets referenced across the project exist and are consistent."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "mcpgateway" / "static"
TEMPLATES_DIR = ROOT / "mcpgateway" / "templates"


# ---------------------------------------------------------------------------
# 1. Static assets referenced by HTML templates exist on disk
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = (".png", ".svg", ".ico", ".gif", ".jpg", ".jpeg", ".webp")


def _extract_static_image_paths(template: Path) -> list[str]:
    """Extract /static/... image src paths from a Jinja2 template."""
    text = template.read_text()
    paths = re.findall(r'src="[^"]*?/static/([^"]+)"', text)
    return [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTENSIONS]


TEMPLATE_FILES = ["admin.html", "login.html", "change-password-required.html"]


@pytest.mark.parametrize("template_name", TEMPLATE_FILES)
def test_template_logo_assets_exist(template_name: str):
    """Every static image referenced in a template must exist on disk."""
    template = TEMPLATES_DIR / template_name
    assert template.exists(), f"Template {template_name} not found"
    paths = _extract_static_image_paths(template)
    assert paths, f"No static image paths found in {template_name}"
    for filename in paths:
        assert (STATIC_DIR / filename).exists(), (
            f"{template_name} references static/{filename} but file does not exist"
        )


# ---------------------------------------------------------------------------
# 2. Docs theme logo exists
# ---------------------------------------------------------------------------

def test_docs_theme_logo_exists():
    """The logo configured in docs/base.yml must exist in docs/theme/."""
    base_yml = ROOT / "docs" / "base.yml"
    assert base_yml.exists(), "docs/base.yml not found"
    # Use regex because base.yml contains MkDocs-specific YAML tags (!!python/name)
    match = re.search(r'^\s*logo:\s*"([^"]+)"', base_yml.read_text(), re.MULTILINE)
    assert match, "No theme logo configured in docs/base.yml"
    logo = match.group(1)
    assert (ROOT / "docs" / "theme" / logo).exists(), (
        f"docs/base.yml references theme logo '{logo}' but file does not exist"
    )


# ---------------------------------------------------------------------------
# 3. README banner image exists
# ---------------------------------------------------------------------------

def test_readme_banner_image_exists():
    """The contextforge banner image in README.md must exist on disk."""
    readme = ROOT / "README.md"
    assert readme.exists(), "README.md not found"
    # Match markdown image syntax: ![alt](path) — only check contextforge images
    matches = re.findall(r"!\[.*?\]\(([^)]*contextforge[^)]+)\)", readme.read_text())
    assert matches, "No contextforge banner image found in README.md"
    for img_path in matches:
        if img_path.startswith("http"):
            continue
        assert (ROOT / img_path).exists(), (
            f"README.md references '{img_path}' but file does not exist"
        )


# ---------------------------------------------------------------------------
# 4. No references to the removed old logo.png
# ---------------------------------------------------------------------------

REMOVED_LOGO = "logo.png"


@pytest.mark.parametrize("template_name", TEMPLATE_FILES)
def test_no_reference_to_removed_logo(template_name: str):
    """Templates must not reference the removed /static/logo.png."""
    template = TEMPLATES_DIR / template_name
    if not template.exists():
        pytest.skip(f"{template_name} not found")
    paths = _extract_static_image_paths(template)
    assert REMOVED_LOGO not in paths, (
        f"{template_name} still references the removed static/{REMOVED_LOGO}"
    )


# ---------------------------------------------------------------------------
# 5. Helm chart icon URL uses new asset (not old logo.png)
# ---------------------------------------------------------------------------

def test_helm_chart_icon_not_old_logo():
    """Helm Chart.yaml icon must not point to the old docs/theme/logo.png."""
    chart = ROOT / "charts" / "mcp-stack" / "Chart.yaml"
    assert chart.exists(), "charts/mcp-stack/Chart.yaml not found"
    match = re.search(r"^icon:\s*(.+)$", chart.read_text(), re.MULTILINE)
    assert match, "No icon field found in Chart.yaml"
    icon = match.group(1).strip()
    assert "logo.png" not in icon, (
        f"Helm Chart.yaml icon still references old logo.png: {icon}"
    )


# ---------------------------------------------------------------------------
# 6. Logo img tags have alt text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_name", TEMPLATE_FILES)
def test_logo_images_have_alt_text(template_name: str):
    """All <img> tags for logos/icons in templates must include alt text."""
    template = TEMPLATES_DIR / template_name
    if not template.exists():
        pytest.skip(f"{template_name} not found")
    text = template.read_text()
    # Find <img> tags that reference contextforge assets
    img_tags = re.findall(r"<img\b[^>]*contextforge[^>]*>", text)
    for tag in img_tags:
        assert 'alt="' in tag, (
            f'{template_name} has a contextforge <img> without alt text: {tag[:80]}'
        )
