#!/usr/bin/env bash
# Tear down the rate-limiter TLS+AUTH e2e stack.
set -euo pipefail
docker rm -f rl-gw rl-pg rl-redis rl-fast-time >/dev/null 2>&1 || true
docker network rm rl-net >/dev/null 2>&1 || true
echo "✅ removed rl-gw, rl-pg, rl-redis, rl-fast-time and the rl-net network"
