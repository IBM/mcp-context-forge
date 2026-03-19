#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="$(dirname "$0")/templates/go"

if ! command -v cookiecutter >/dev/null 2>&1; then
  echo "Error: 'cookiecutter' is not installed. Install with: pip install cookiecutter" >&2
  exit 1
fi

if [ $# -lt 1 ]; then
  echo "Usage: $0 <name-or-destination> [cookiecutter options...]" >&2
  echo "  Examples:" >&2
  echo "    $0 fast_time_server           # creates ./go/fast_time_server" >&2
  echo "    $0 go/clock                   # explicit destination path" >&2
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

OUTPUT_DIR="$(dirname "$DEST")"
PROJECT_SLUG="$(basename "$DEST")"

mkdir -p "$OUTPUT_DIR"

echo "Scaffolding Go MCP server into: $DEST"
cookiecutter "$TEMPLATE_DIR" -o "$OUTPUT_DIR" project_slug="$PROJECT_SLUG" "$@"

echo "Done. Next steps:"
echo "  cd $DEST"
echo "  go mod tidy"
echo "  make run   # build & run (stdio)"
