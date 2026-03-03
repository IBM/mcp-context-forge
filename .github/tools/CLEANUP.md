# GHCR Cleanup Script

Prunes old container image versions from `ghcr.io/ibm/mcp-context-forge`.

## What it keeps

- **Release tags**: `latest`, `v*`, and bare semver (`X.Y.Z`)
- **Recent images**: anything younger than `KEEP_DAYS` (default 7)

## What it deletes

- SHA-tagged build images (`amd64-abc123`, `arm64-...`, `s390x-...`)
- Cosign signatures and attestations (`sha256-....sig`, `sha256-....att`)
- Untagged/orphaned manifests

## Prerequisites

```bash
# GitHub CLI with delete:packages scope
gh auth refresh -h github.com -s read:packages,delete:packages

# Verify
gh auth status -t
```

## Usage

### Dry-run (default — shows what would be deleted, deletes nothing)

```bash
# See everything that would be cleaned up
bash .github/tools/cleanup-ghcr-versions.sh --yes

# Filter to a specific month
MONTH=2025-06 bash .github/tools/cleanup-ghcr-versions.sh --yes

# Limit to 10 images (for testing)
MAX_DELETE=10 bash .github/tools/cleanup-ghcr-versions.sh --yes

# Combine: 10 images from June 2025
MONTH=2025-06 MAX_DELETE=10 bash .github/tools/cleanup-ghcr-versions.sh --yes
```

### Actual deletion

```bash
# Delete all old images (interactive confirmation)
DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh

# Delete without confirmation (for CI)
DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh --yes

# Delete month by month (recommended for initial cleanup)
MONTH=2025-05 DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh --yes
MONTH=2025-06 DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh --yes
MONTH=2025-07 DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh --yes
# ... etc

# Test with 10 deletions first
MONTH=2025-05 MAX_DELETE=10 DRY_RUN=false bash .github/tools/cleanup-ghcr-versions.sh --yes
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN` | `true` | Set to `false` to actually delete |
| `KEEP_DAYS` | `7` | Keep images younger than N days |
| `MONTH` | _(all)_ | Only process images from this month, e.g. `2025-06` |
| `MAX_DELETE` | `0` (unlimited) | Stop after deleting N images |
| `ORG` | `ibm` | GitHub organization |
| `PKG` | `mcp-context-forge` | Package name |
| `GITHUB_TOKEN` / `GH_TOKEN` | _(gh auth)_ | Authentication token |

## Rate limiting

Deletions run in waves of 30 with a 10-second pause between waves (~120 deletes/min). GitHub's secondary rate limit is 180 mutating requests/min, so this stays safely under.

## Automated cleanup

The `ghcr-cleanup.yml` workflow runs this script weekly (Sunday 04:30 UTC) with `DRY_RUN=false`. Manual dispatch defaults to `DRY_RUN=true` for safety.
