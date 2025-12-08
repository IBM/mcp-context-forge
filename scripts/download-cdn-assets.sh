#!/bin/bash
# Script to download CDN assets for airgapped deployment
# This script is executed during container build to fetch all external CSS/JS dependencies

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="${SCRIPT_DIR}/../app/mcpgateway/static/vendor"

# Create vendor directory structure
mkdir -p "${STATIC_DIR}/tailwindcss"
mkdir -p "${STATIC_DIR}/htmx"
mkdir -p "${STATIC_DIR}/codemirror/mode/javascript"
mkdir -p "${STATIC_DIR}/codemirror/theme"
mkdir -p "${STATIC_DIR}/alpinejs"
mkdir -p "${STATIC_DIR}/chartjs"

echo "📦 Downloading CDN assets for airgapped deployment..."

# Download Tailwind CSS standalone build
echo "  ⬇️  Tailwind CSS..."
curl -fsSL "https://cdn.tailwindcss.com" \
  -o "${STATIC_DIR}/tailwindcss/tailwind.min.js"

# Download HTMX
echo "  ⬇️  HTMX 1.9.10..."
curl -fsSL "https://unpkg.com/htmx.org@1.9.10" \
  -o "${STATIC_DIR}/htmx/htmx.min.js"

# Download CodeMirror
echo "  ⬇️  CodeMirror 5.65.18..."
curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/codemirror.min.js" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/javascript/javascript.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/javascript/javascript.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/codemirror.min.css" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.css"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/theme/monokai.min.css" \
  -o "${STATIC_DIR}/codemirror/theme/monokai.min.css"

# Download Alpine.js (pinned to 3.14.1 for reproducibility)
echo "  ⬇️  Alpine.js 3.14.1..."
curl -fsSL "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js" \
  -o "${STATIC_DIR}/alpinejs/alpine.min.js"

# Download Chart.js (pinned to 4.4.1 for reproducibility)
echo "  ⬇️  Chart.js 4.4.1..."
curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" \
  -o "${STATIC_DIR}/chartjs/chart.umd.min.js"

echo "✅ All CDN assets downloaded successfully to ${STATIC_DIR}"
echo ""
echo "Directory structure:"
find "${STATIC_DIR}" -type f | sort
