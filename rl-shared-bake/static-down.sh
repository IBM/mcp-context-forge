#!/usr/bin/env bash
# Tear down the ISOLATED static-config stack (leaves the dynamic rl-* stack alone).
set -euo pipefail
docker rm -f rl-static-gw rl-static-pg rl-static-redis rl-static-fast-time >/dev/null 2>&1 || true
docker network rm rl-static-net >/dev/null 2>&1 || true
echo "✅ removed rl-static-gw, rl-static-pg, rl-static-redis, rl-static-fast-time and rl-static-net"
