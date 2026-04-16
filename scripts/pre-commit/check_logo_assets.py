#!/usr/bin/env python3
"""Pre-commit hook: verify logo and image asset references.

Checks that:
- Static images referenced in HTML templates exist on disk
- Docs theme logo exists
- README banner image exists
- No references to the removed old logo.png
- Helm chart icon does not reference old logo
- Logo img tags have alt text

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "mcpgateway" / "static"
TEMPLATES_DIR = REPO_ROOT / "mcpgateway" / "templates"
IMAGE_EXTENSIONS = (".png", ".svg", ".ico", ".gif", ".jpg", ".jpeg", ".webp")
TEMPLATE_FILES = ["admin.html", "login.html", "change-password-required.html"]
REMOVED_LOGO = "logo.png"


def _extract_static_image_paths(template: Path) -> list[str]:
    text = template.read_text()
    paths = re.findall(r'src="[^"]*?/static/([^"]+)"', text)
    return [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTENSIONS]


def main() -> int:
    violations: list[str] = []

    # Template logo assets exist on disk
    for template_name in TEMPLATE_FILES:
        template = TEMPLATES_DIR / template_name
        if not template.exists():
            continue

        paths = _extract_static_image_paths(template)
        for filename in paths:
            if not (STATIC_DIR / filename).exists():
                violations.append(f"{template_name}: references static/{filename} but file does not exist")

        # No reference to removed logo
        if REMOVED_LOGO in paths:
            violations.append(f"{template_name}: still references the removed static/{REMOVED_LOGO}")

        # Logo img tags have alt text
        text = template.read_text()
        img_tags = re.findall(r"<img\b[^>]*contextforge[^>]*>", text)
        for tag in img_tags:
            if 'alt="' not in tag:
                violations.append(f"{template_name}: contextforge <img> without alt text: {tag[:80]}")

    # Docs theme logo exists
    base_yml = REPO_ROOT / "docs" / "base.yml"
    if base_yml.exists():
        match = re.search(r'^\s*logo:\s*"([^"]+)"', base_yml.read_text(), re.MULTILINE)
        if match:
            logo = match.group(1)
            if not (REPO_ROOT / "docs" / "theme" / logo).exists():
                violations.append(f"docs/base.yml: theme logo '{logo}' does not exist")

    # README banner image exists
    readme = REPO_ROOT / "README.md"
    if readme.exists():
        matches = re.findall(r"!\[.*?\]\(([^)]*contextforge[^)]+)\)", readme.read_text())
        for img_path in matches:
            if not img_path.startswith("http") and not (REPO_ROOT / img_path).exists():
                violations.append(f"README.md: references '{img_path}' but file does not exist")

    # Helm chart icon not old logo
    chart = REPO_ROOT / "charts" / "mcp-stack" / "Chart.yaml"
    if chart.exists():
        match = re.search(r"^icon:\s*(.+)$", chart.read_text(), re.MULTILINE)
        if match and "logo.png" in match.group(1):
            violations.append(f"Chart.yaml: icon still references old logo.png")

    if violations:
        print("Logo/asset violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
