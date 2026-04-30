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
mkdir -p "${STATIC_DIR}/fontawesome/css"
mkdir -p "${STATIC_DIR}/fontawesome/webfonts"

echo "📦 Downloading CDN assets for airgapped deployment..."

# Download Tailwind Play CDN (version-pinned v3 for window.tailwind.config compatibility)
echo "  ⬇️  Tailwind CSS..."
curl -fsSL "https://cdn.tailwindcss.com/3.4.17" \
  -o "${STATIC_DIR}/tailwindcss/tailwind.min.js"

# Download HTMX
echo "  ⬇️  HTMX 1.9.12..."
curl -fsSL "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js" \
  -o "${STATIC_DIR}/htmx/htmx.min.js"

# Download CodeMirror
echo "  ⬇️  CodeMirror 5.65.20..."
curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.js" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/javascript/javascript.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/javascript/javascript.min.js"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.css" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.css"

curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/monokai.min.css" \
  -o "${STATIC_DIR}/codemirror/theme/monokai.min.css"

# Download Alpine.js (pinned to 3.15.11 for reproducibility)
echo "  ⬇️  Alpine.js 3.15.8..."
curl -fsSL "https://cdn.jsdelivr.net/npm/alpinejs@3.15.11/dist/cdn.min.js" \
  -o "${STATIC_DIR}/alpinejs/alpine.min.js"

# Download Chart.js (pinned to 4.5.1 for reproducibility)
echo "  ⬇️  Chart.js 4.5.1..."
curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js" \
  -o "${STATIC_DIR}/chartjs/chart.umd.min.js"

# Download Marked (Markdown parser, pinned to 18.0.2 for reproducibility)
echo "  ⬇️  Marked 18.0.2..."
mkdir -p "${STATIC_DIR}/marked"
curl -fsSL "https://cdn.jsdelivr.net/npm/marked@18.0.2/lib/marked.umd.js" \
  -o "${STATIC_DIR}/marked/marked.min.js"

# Download DOMPurify (XSS sanitizer, pinned to 3.4.1 for reproducibility)
echo "  ⬇️  DOMPurify 3.4.1..."
mkdir -p "${STATIC_DIR}/dompurify"
curl -fsSL "https://cdn.jsdelivr.net/npm/dompurify@3.4.1/dist/purify.min.js" \
  -o "${STATIC_DIR}/dompurify/purify.min.js"

# Download Font Awesome (pinned to 7.0.1 for reproducibility)
echo "  ⬇️  Font Awesome 7.0.1..."
curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.1/css/all.min.css" \
  -o "${STATIC_DIR}/fontawesome/css/all.min.css"

# Download Font Awesome webfonts (required for the CSS to work)
echo "  ⬇️  Font Awesome webfonts..."
for font in fa-solid-900.woff2 fa-regular-400.woff2 fa-brands-400.woff2; do
  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.1/webfonts/${font}" \
    -o "${STATIC_DIR}/fontawesome/webfonts/${font}"
done

# Fix Font Awesome CSS paths for local serving (change ../webfonts to ./webfonts)
sed -i 's|../webfonts|./webfonts|g' "${STATIC_DIR}/fontawesome/css/all.min.css"

echo "✅ All CDN assets downloaded successfully to ${STATIC_DIR}"
echo ""
echo "Directory structure:"
find "${STATIC_DIR}" -type f | sort
