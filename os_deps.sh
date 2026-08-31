#!/usr/bin/env bash
#
# scripts/os_deps.sh - install/verify Graphviz, Pandoc, SCC
# Supports macOS (Intel/Apple-Silicon), Debian/Ubuntu, RHEL/Fedora,
#          generic Linux, Windows (prints manual steps).
# ──────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ───────────────────────── helpers ─────────────────────────
have()    { command -v "$1" >/dev/null 2>&1; }
need()    { ! have "$1"; }                    # true if command missing
sudo_if() { [ "$(id -u)" -ne 0 ] && echo "sudo"; }

install_scc() {
  local ver="v3.5.0" os="$1" arch="$2" file url tmp
  file="scc_${os}_${arch}"
  [[ "$os" == "Windows" ]] && file="${file}.zip" || file="${file}.tar.gz"
  url="https://github.com/boyter/scc/releases/download/${ver}/${file}"

  echo "⬇️  Installing scc from $url"
  tmp=$(mktemp -d)
  curl -sSL "$url" -o "$tmp/scc_pkg"
  if [[ "$file" == *.zip ]]; then unzip -q "$tmp/scc_pkg" -d "$tmp"
  else tar -xf "$tmp/scc_pkg" -C "$tmp"; fi
  $(sudo_if) mv "$tmp/scc" /usr/local/bin/
  $(sudo_if) chmod +x /usr/local/bin/scc
  rm -rf "$tmp"
  echo "✅  scc installed."
}

# ───────────────────────── main logic ─────────────────────────
echo "🔍  Checking platform prerequisites ..."
MISSING=()
for cmd in dot pandoc scc; do
  need "$cmd" && MISSING+=("$cmd")
done

[[ ${#MISSING[@]} -eq 0 ]] && { echo "✅  All commands present."; exit 0; }
echo "⚠️  Missing: ${MISSING[*]}"

OS=$(uname -s)
ARCH=$(uname -m)
case "$ARCH" in
  aarch64|arm64) ARCH_TAG="arm64" ;;
  x86_64|amd64)  ARCH_TAG="x86_64" ;;
  i*86)          ARCH_TAG="i386" ;;
  *)             ARCH_TAG="$ARCH" ;;
esac
echo "🏷️  Detected $OS / $ARCH_TAG"

# ───────────────────────── per-OS actions ─────────────────────────
if [[ "$OS" == "Darwin" ]]; then
  have brew || { echo "❌  Homebrew missing → https://brew.sh"; exit 1; }
  need dot    && brew install graphviz
  need pandoc && brew install pandoc
  need scc    && install_scc "Darwin" "$ARCH_TAG"

elif [[ "$OS" == "Linux" ]]; then
  if have apt-get; then
       PKG_MGR="apt-get"
       INSTALL="$(sudo_if) apt-get install -y --no-install-recommends"
       $(sudo_if) apt-get update -qq
       need graphviz && $INSTALL graphviz
       need pandoc   && $INSTALL pandoc
  elif have dnf || have yum; then
       PKG_MGR=$(have dnf && echo dnf || echo yum)
       INSTALL="$(sudo_if) $PKG_MGR install -y"
       $(sudo_if) $PKG_MGR -y update || true
       need graphviz && $INSTALL graphviz
       need pandoc   && $INSTALL pandoc
  else
       echo "❌  Unsupported Linux package manager - please install Graphviz, Pandoc, and SCC manually."
  fi
  need scc && install_scc "Linux" "$ARCH_TAG"

elif [[ "$OS" =~ MINGW|MSYS|CYGWIN ]]; then
  echo "ℹ️  On Windows please install:"
  echo "    - Graphviz (https://graphviz.org)"
  echo "    - Pandoc   (https://pandoc.org/installing.html)"
  need scc && install_scc "Windows" "$ARCH_TAG"

else
  echo "❌  Unsupported OS - manual install required."
  exit 1
fi

echo "🎉  Done."
