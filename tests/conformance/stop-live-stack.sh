#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
pid_file="${repo_root}/conformance-logs/reference-server.pid"

if [ -f "${pid_file}" ]; then
  kill "$(cat "${pid_file}")" 2>/dev/null || true
fi

docker compose -f "${script_dir}/docker-compose.yml" \
  down --volumes --remove-orphans
