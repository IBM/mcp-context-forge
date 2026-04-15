#!/usr/bin/env python3
"""Score all open PRs against the ContextForge risk rubric and output CSV.

Usage:
    python3 score_prs.py <pr_json> <file_list_dir> <output_csv> [approvals_csv]

Arguments:
    pr_json        Path to JSON file from `gh pr list --json ...`
    file_list_dir  Directory containing per-PR file lists (<number>.txt)
    output_csv     Path to write the scored CSV
    approvals_csv  Optional CSV with columns: pr_number,approvals
"""

# Standard
import csv
import json
import os
import re
import sys

# ── Zone mapping ──────────────────────────────────────────────────────────────
# Each pattern maps to (zone_name, score). First match wins per file.
ZONE_RULES = [
    # Z4 - Auth core (4 pts)
    (re.compile(r"mcpgateway/auth\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/middleware/token_scoping\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/middleware/rbac\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/middleware/auth_middleware\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/middleware/http_auth_middleware\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/services/permission_service\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/routers/auth\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/routers/oauth_router\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/routers/tokens\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/routers/sso\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/services/sso_service\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/common/oauth\.py"), "Z4-Auth", 4),
    (re.compile(r"mcpgateway/services/email_auth_service\.py"), "Z4-Auth", 4),
    # Z3 - Transport/session (3 pts)
    (re.compile(r"mcpgateway/transports/"), "Z3-Transport", 3),
    (re.compile(r"mcpgateway/services/mcp_session_pool\.py"), "Z3-Transport", 3),
    (re.compile(r"mcpgateway/cache/session_registry\.py"), "Z3-Transport", 3),
    # Z3 - Data model / connections (3 pts)
    (re.compile(r"mcpgateway/db\.py"), "Z3-Data", 3),
    (re.compile(r"mcpgateway/schemas\.py"), "Z3-Data", 3),
    (re.compile(r"mcpgateway/alembic/versions/"), "Z3-Data", 3),
    # Z3 - Config/flags (3 pts)
    (re.compile(r"mcpgateway/config\.py"), "Z3-Config", 3),
    # Z3 - Per-request middleware (3 pts)
    (re.compile(r"mcpgateway/middleware/token_usage_middleware\.py"), "Z3-Middleware", 3),
    # Z2 - Plugin framework (2 pts)
    (re.compile(r"mcpgateway/plugins/framework/"), "Z2-Plugin", 2),
    # Z2 - Cache / pooling (2 pts)
    (re.compile(r"mcpgateway/cache/"), "Z2-Cache", 2),
    # Z2 - Business logic (2 pts)
    (re.compile(r"mcpgateway/services/"), "Z2-Business", 2),
    (re.compile(r"mcpgateway/routers/"), "Z2-Business", 2),
    (re.compile(r"mcpgateway/main\.py"), "Z2-Business", 2),
    (re.compile(r"mcpgateway/middleware/"), "Z2-Business", 2),
    # Z1 - Admin UI (1 pt) — must precede the mcpgateway/ catch-all
    (re.compile(r"mcpgateway/admin\.py"), "Z1-UI", 1),
    (re.compile(r"mcpgateway/templates/"), "Z1-UI", 1),
    (re.compile(r"mcpgateway/static/"), "Z1-UI", 1),
    # Z2 - Other mcpgateway code (catch-all — keep last among mcpgateway/ rules)
    (re.compile(r"mcpgateway/"), "Z2-Business", 2),
    # Z2 - Plugin implementations
    (re.compile(r"plugins/"), "Z2-Plugin", 2),
    # Z0 - Everything else
    (re.compile(r"tests/"), "Z0-Tests", 0),
    (re.compile(r"docs/"), "Z0-Docs", 0),
    (re.compile(r"\.github/"), "Z0-CI", 0),
    (re.compile(r"charts/"), "Z0-Charts", 0),
    (re.compile(r"llms/"), "Z0-Docs", 0),
    (re.compile(r"infra/"), "Z0-Infra", 0),
    (re.compile(r"run-gunicorn\.sh"), "Z0-Infra", 0),
]


def classify_file(path):
    """Return (zone_name, score) for a file path."""
    for pattern, name, score in ZONE_RULES:
        if pattern.search(path):
            return name, score
    return "Z0-Other", 0


def compute_zone_score(files):
    """Dimension 1: sum per-file zone scores, cap at 10."""
    total = sum(classify_file(f)[1] for f in files)
    return min(total, 10)


def compute_size_score(additions, deletions, changed_files):
    """Dimension 2: size bracket scoring."""
    lines = additions + deletions
    if lines > 4000:
        lines_score = 5
    elif lines > 1500:
        lines_score = 4
    elif lines > 500:
        lines_score = 3
    elif lines > 200:
        lines_score = 2
    elif lines > 50:
        lines_score = 1
    else:
        lines_score = 0
    if changed_files > 30:
        files_score = 5
    elif changed_files > 15:
        files_score = 4
    elif changed_files > 10:
        files_score = 3
    elif changed_files > 6:
        files_score = 2
    elif changed_files > 3:
        files_score = 1
    else:
        files_score = 0
    return max(lines_score, files_score)


def compute_structural_score(files):
    """Dimension 3: structural impact, additive, cap at 5."""
    score = 0
    has_migration = any("alembic/versions/" in f for f in files)
    has_db_model = any(f.endswith("mcpgateway/db.py") or f == "mcpgateway/db.py" for f in files)
    has_main = any(f.endswith("mcpgateway/main.py") or f == "mcpgateway/main.py" for f in files)
    has_config_flags = any(f.endswith("mcpgateway/config.py") or f == "mcpgateway/config.py" for f in files)
    has_transport_auth = any("mcpgateway/transports/" in f for f in files)
    has_new_router = any("mcpgateway/routers/" in f for f in files)

    if has_migration:
        score += 2
    if has_db_model:
        score += 2
    if has_main:
        score += 1
    if has_config_flags:
        score += 1
    if has_transport_auth:
        score += 2
    if has_new_router:
        score += 1
    return min(score, 5)


def compute_security_score(files, labels):
    """Dimension 4: security invariant impact, additive, cap at 5."""
    score = 0
    label_names = {lbl["name"] for lbl in labels}

    has_token_scoping = any("token_scoping.py" in f for f in files)
    has_rbac = any("middleware/rbac.py" in f for f in files)
    has_auth_core = any(f.endswith("mcpgateway/auth.py") or f == "mcpgateway/auth.py" for f in files)
    has_oauth = any("oauth_router.py" in f or "oauth.py" in f for f in files)
    has_tokens = any("routers/tokens.py" in f for f in files)

    if has_token_scoping and has_rbac:
        score += 3
    if has_auth_core:
        score += 2
    if has_oauth:
        score += 1
    if has_tokens:
        score += 1
    if "security" in label_names:
        score += 1
    return min(score, 5)


PROD_PREFIXES = ("mcpgateway/", "plugins/", "a2a-agents/", "mcp-servers/", "tools_rust/")


def compute_test_score(files):
    """Dimension 5: test adequacy penalty, cap at 5."""
    prod_files = [f for f in files if any(f.startswith(p) for p in PROD_PREFIXES)]
    test_files = [f for f in files if f.startswith("tests/")]

    if not prod_files:
        return 0
    if not test_files:
        return 3
    return 0


def compute_perf_score(files):
    """Dimension 6: performance impact, additive, cap at 5."""
    score = 0
    has_db_engine = any(f.endswith("mcpgateway/db.py") or f == "mcpgateway/db.py" for f in files)
    has_per_request_mw = any("middleware/rbac.py" in f or "middleware/token_usage_middleware.py" in f or "middleware/auth_middleware.py" in f for f in files)
    has_cache = any("mcpgateway/cache/" in f for f in files)
    has_gunicorn = any("run-gunicorn" in f for f in files)
    has_services = any("mcpgateway/services/" in f for f in files)

    if has_db_engine:
        score += 3
    if has_per_request_mw:
        score += 2
    if has_cache:
        score += 2
    if has_gunicorn:
        score += 2
    if has_services and not has_db_engine and not has_per_request_mw:
        score += 1
    return min(score, 5)


def assign_tier(total):
    """Map total score to tier."""
    if total >= 20:
        return "1-Deep"
    elif total >= 11:
        return "2-Standard"
    elif total >= 5:
        return "3-Focused"
    else:
        return "4-Quick"


def main():
    """Score open PRs and write results to CSV."""
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print(f"Usage: {sys.argv[0]} <pr_json> <file_list_dir> <output_csv> [approvals_csv]", file=sys.stderr)
        sys.exit(1)

    pr_json_path, file_list_dir, output_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    approvals_csv = sys.argv[4] if len(sys.argv) == 5 else None

    with open(pr_json_path, encoding="utf-8") as f:
        prs = json.load(f)

    # Load approvals if provided (CSV: pr_number,approvals)
    approvals_map = {}
    if approvals_csv:
        with open(approvals_csv, encoding="utf-8") as af:
            for line in af:
                line = line.strip()
                if not line or line.startswith("pr_number"):
                    continue
                parts = line.split(",", 1)
                if len(parts) == 2:
                    approvals_map[int(parts[0])] = int(parts[1])

    rows = []
    for pr in sorted(prs, key=lambda x: x["number"]):
        num = pr["number"]
        files_path = os.path.join(file_list_dir, f"{num}.txt")
        if os.path.exists(files_path):
            with open(files_path, encoding="utf-8") as ff:
                files = [line.strip() for line in ff if line.strip()]
        else:
            files = []

        zone = compute_zone_score(files)
        size = compute_size_score(pr["additions"], pr["deletions"], pr["changedFiles"])
        struct = compute_structural_score(files)
        sec = compute_security_score(files, pr.get("labels", []))
        test = compute_test_score(files)
        perf = compute_perf_score(files)
        total = zone + size + struct + sec + test + perf
        tier = assign_tier(total)

        label_names = ", ".join(lbl["name"] for lbl in pr.get("labels", []))
        author = pr.get("author", {}).get("login", "unknown")
        title = pr["title"][:80]

        url = pr.get("url", f"https://github.com/IBM/mcp-context-forge/pull/{num}")

        rows.append(
            {
                "PR": num,
                "URL": url,
                "Title": title,
                "Author": author,
                "Approvals": approvals_map.get(num, 0),
                "Files": pr["changedFiles"],
                "Additions": pr["additions"],
                "Deletions": pr["deletions"],
                "Zone": zone,
                "Size": size,
                "Structural": struct,
                "Security": sec,
                "TestGap": test,
                "Perf": perf,
                "Total": total,
                "Tier": tier,
                "Labels": label_names,
            }
        )

    fieldnames = ["PR", "URL", "Title", "Author", "Approvals", "Files", "Additions", "Deletions", "Zone", "Size", "Structural", "Security", "TestGap", "Perf", "Total", "Tier", "Labels"]
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    tier_counts = {}
    for r in rows:
        tier_counts[r["Tier"]] = tier_counts.get(r["Tier"], 0) + 1

    print(f"Scored {len(rows)} PRs -> {output_csv}")
    print()
    for tier in sorted(tier_counts.keys()):
        print(f"  {tier}: {tier_counts[tier]} PRs")


if __name__ == "__main__":
    main()
