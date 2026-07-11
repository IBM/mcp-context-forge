#!/bin/bash
# Script to download CDN assets for airgapped deployment
# This script is executed during container build to fetch all external CSS/JS dependencies

set -euo pipefail

# Retry wrapper: retries a command up to 3 times with exponential backoff
retry() {
    local n=0 max=3 delay=2
    until "$@"; do
        n=$((n + 1))
        if (( n >= max )); then
            echo "❌ Command failed after ${max} attempts: $*" >&2
            return 1
        fi
        echo "⚠️  Command failed (attempt ${n}/${max}), retrying in ${delay}s..." >&2
        sleep "${delay}"
        delay=$((delay * 2))
    done
}


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="${SCRIPT_DIR}/../app/mcpgateway/static/vendor"

# Create vendor directory structure
mkdir -p "${STATIC_DIR}/tailwindcss"
mkdir -p "${STATIC_DIR}/codemirror/mode/javascript"
mkdir -p "${STATIC_DIR}/codemirror/theme"
mkdir -p "${STATIC_DIR}/chartjs"
mkdir -p "${STATIC_DIR}/fontawesome/css"
mkdir -p "${STATIC_DIR}/fontawesome/webfonts"

echo "📦 Downloading CDN assets for airgapped deployment..."

# Download Tailwind Play CDN (version-pinned v3 for window.tailwind.config compatibility)
echo "  ⬇️  Tailwind CSS 3.4.17..."
retry curl -fsSL "https://cdn.tailwindcss.com/3.4.17" \
  -o "${STATIC_DIR}/tailwindcss/tailwind.min.js"

# Download CodeMirror
echo "  ⬇️  CodeMirror 5.65.20..."
retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.js" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.js"

retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/javascript/javascript.min.js" \
  -o "${STATIC_DIR}/codemirror/mode/javascript/javascript.min.js"

retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.css" \
  -o "${STATIC_DIR}/codemirror/codemirror.min.css"

retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/monokai.min.css" \
  -o "${STATIC_DIR}/codemirror/theme/monokai.min.css"

# Download Chart.js (pinned to 4.5.1 for reproducibility)
echo "  ⬇️  Chart.js 4.5.1..."
retry curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js" \
  -o "${STATIC_DIR}/chartjs/chart.umd.min.js"

# Download Marked (Markdown parser, pinned to 18.0.5 for reproducibility)
echo "  ⬇️  Marked 18.0.5..."
mkdir -p "${STATIC_DIR}/marked"
retry curl -fsSL "https://cdn.jsdelivr.net/npm/marked@18.0.5/lib/marked.umd.js" \
  -o "${STATIC_DIR}/marked/marked.min.js"

# Download DOMPurify (XSS sanitizer, pinned to 3.4.11 for reproducibility)
echo "  ⬇️  DOMPurify 3.4.11..."
mkdir -p "${STATIC_DIR}/dompurify"
retry curl -fsSL "https://cdn.jsdelivr.net/npm/dompurify@3.4.11/dist/purify.min.js" \
  -o "${STATIC_DIR}/dompurify/purify.min.js"

# Download Font Awesome (pinned to 7.0.1 for reproducibility)
echo "  ⬇️  Font Awesome 7.0.1..."
retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.1/css/all.min.css" \
  -o "${STATIC_DIR}/fontawesome/css/all.min.css"

# Download Font Awesome webfonts (required for the CSS to work)
echo "  ⬇️  Font Awesome webfonts..."
for font in fa-solid-900.woff2 fa-regular-400.woff2 fa-brands-400.woff2; do
  retry curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.1/webfonts/${font}" \
    -o "${STATIC_DIR}/fontawesome/webfonts/${font}"
done

# Fix Font Awesome CSS paths for local serving (change ../webfonts to ./webfonts)
sed -i 's|../webfonts|./webfonts|g' "${STATIC_DIR}/fontawesome/css/all.min.css"

echo "✅ All CDN assets downloaded successfully to ${STATIC_DIR}"
echo ""
echo "Directory structure:"
find "${STATIC_DIR}" -type f | sort
