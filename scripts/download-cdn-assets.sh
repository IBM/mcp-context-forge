#!/bin/bash
# Script to download CDN assets for airgapped deployment
# This script is executed during container build to fetch all external CSS/JS dependencies

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="${SCRIPT_DIR}/../app/mcpgateway/static/vendor"

# Create vendor directory structure
mkdir -p "${STATIC_DIR}/tailwindcss"
mkdir -p "${STATIC_DIR}/htmx"
mkdir -p "${STATIC_DIR}/codemirror/addon/mode"
mkdir -p "${STATIC_DIR}/codemirror/mode/javascript"
mkdir -p "${STATIC_DIR}/codemirror/mode/python"
mkdir -p "${STATIC_DIR}/codemirror/mode/shell"
mkdir -p "${STATIC_DIR}/codemirror/mode/go"
mkdir -p "${STATIC_DIR}/codemirror/mode/rust"
mkdir -p "${STATIC_DIR}/codemirror/theme"
mkdir -p "${STATIC_DIR}/alpinejs"
mkdir -p "${STATIC_DIR}/chartjs"
mkdir -p "${STATIC_DIR}/fontawesome/css"
mkdir -p "${STATIC_DIR}/fontawesome/webfonts"

echo "📦 Downloading CDN assets for airgapped deployment..."

# Download Tailwind Play CDN (version-pinned v3 for window.tailwind.config compatibility)
echo "  ⬇️  Tailwind CSS..."
curl -fsSL "https://cdn.tailwindcss.com/3.4.17" \
  -o "${STATIC_DIR}/tailwindcss/tailwind.min.js"

# Download HTMX
echo "  ⬇️  HTMX 1.9.10..."
curl -fsSL "https://unpkg.com/htmx.org@1.9.10" \
  -o "${STATIC_DIR}/htmx/htmx.min.js"

# Download CodeMirror
echo "  ⬇️  CodeMirror 5.65.18..."
curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/codemirror.min.js" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/addon/mode/simple.min.js" \
  -o "${STATIC_DIR}/codemirror/addon/mode/simple.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/javascript/javascript.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/javascript/javascript.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/python/python.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/python/python.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/shell/shell.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/shell/shell.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/go/go.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/go/go.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/rust/rust.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/rust/rust.min.js"

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

# Download Marked (Markdown parser, pinned to 11.1.1 for reproducibility)
echo "  ⬇️  Marked 11.1.1..."
mkdir -p "${STATIC_DIR}/marked"
curl -fsSL "https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js" \
  -o "${STATIC_DIR}/marked/marked.min.js"

# Download DOMPurify (XSS sanitizer, pinned to 3.0.6 for reproducibility)
echo "  ⬇️  DOMPurify 3.0.6..."
mkdir -p "${STATIC_DIR}/dompurify"
curl -fsSL "https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js" \
  -o "${STATIC_DIR}/dompurify/purify.min.js"

# Download Font Awesome (pinned to 6.4.0 for reproducibility)
echo "  ⬇️  Font Awesome 6.4.0..."
curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" \
  -o "${STATIC_DIR}/fontawesome/css/all.min.css"

# Download Font Awesome webfonts (required for the CSS to work)
echo "  ⬇️  Font Awesome webfonts..."
for font in fa-solid-900.woff2 fa-regular-400.woff2 fa-brands-400.woff2; do
  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/${font}" \
    -o "${STATIC_DIR}/fontawesome/webfonts/${font}"
done

echo "✅ All CDN assets downloaded successfully to ${STATIC_DIR}"
echo ""
echo "Directory structure:"
find "${STATIC_DIR}" -type f | sort
