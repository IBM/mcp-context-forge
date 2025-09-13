#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="$(dirname "$0")/templates/go"

if ! command -v copier >/dev/null 2>&1; then
  echo "Error: 'copier' is not installed. Install with: pip install copier" >&2
  exit 1
fi

if [ $# -lt 1 ]; then
  echo "Usage: $0 <name-or-destination> [copier options...]" >&2
  echo "  Examples:" >&2
  echo "    $0 fast_time_server           # creates ./go/fast_time_server" >&2
  echo "    $0 go/clock --force           # explicit destination path" >&2
  exit 2
fi

RAW="$1"; shift || true

case "$RAW" in
  */*|./*|/*)
    DEST="$RAW"
    ;;
  *)
    DEST="go/$RAW"
    ;;
esac

mkdir -p "$(dirname "$DEST")"

echo "Scaffolding Go MCP server into: $DEST"
copier copy "$TEMPLATE_DIR" "$DEST" "$@"

echo "Done. Next steps:"
echo "  cd $DEST"
echo "  go mod tidy"
echo "  make run   # build & run (stdio)"
