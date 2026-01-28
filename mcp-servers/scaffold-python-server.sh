#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="$(dirname "$0")/templates/python"

if ! command -v copier >/dev/null 2>&1; then
  echo "Error: 'copier' is not installed. Install with: pip install copier" >&2
  exit 1
fi

if [ $# -lt 1 ]; then
  echo "Usage: $0 <name-or-destination> [copier options...]" >&2
  echo "  Examples:" >&2
  echo "    $0 awesome_server           # creates ./python/awesome_server" >&2
  echo "    $0 python/my_server --force # explicit destination path" >&2
  exit 2
fi

RAW="$1"; shift || true

# If argument looks like a bare name (no slash), place under ./python/
case "$RAW" in
  */*|./*|/*)
    DEST="$RAW"
    ;;
  *)
    DEST="python/$RAW"
    ;;
esac

mkdir -p "$(dirname "$DEST")"

echo "Scaffolding Python MCP server into: $DEST"
copier copy "$TEMPLATE_DIR" "$DEST" "$@"

echo "Done. Next steps:"
echo "  cd $DEST && python -m pip install -e .[dev]"
echo "  make dev   # run stdio server"
