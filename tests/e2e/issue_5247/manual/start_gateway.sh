#!/usr/bin/env bash
# Starts an isolated instance of the real mcpgateway.main:app for e2e testing #5247.
# Runs from a scratch CWD (no .env file there) so pydantic-settings only sees the
# variables exported below, not the repo's real .env.
set -euo pipefail

SCRATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRATCH/../../../.." && pwd)"  # tests/e2e/issue_5247/manual/ -> repo root

rm -f "$SCRATCH/e2e.db"

if [ ! -f "$SCRATCH/e2e.env" ]; then
  cp "$SCRATCH/e2e.env.example" "$SCRATCH/e2e.env"
fi

set -a
# shellcheck source=/dev/null
source "$SCRATCH/e2e.env"
set +a

cd "$SCRATCH"
exec "$REPO/.venv/bin/uvicorn" mcpgateway.main:app \
  --app-dir "$REPO" \
  --host 127.0.0.1 --port 48444 --log-level warning
