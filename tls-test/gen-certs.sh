#!/usr/bin/env bash
# Generate a self-signed CA + Redis server cert for the TLS smoke test stack.
#
# Outputs into mcp-context-forge/tls-certs/ (sibling of this script's parent
# directory). Re-run is idempotent — overwrites any existing files.
#
# What gets created:
#   ca.key, ca.crt        — local self-signed CA
#   redis.key, redis.crt  — Redis server cert signed by ca.crt
#                           SAN: DNS=redis, DNS=redis-tls, DNS=localhost,
#                                IP=127.0.0.1
#
# The CA is trusted by the gateway image at build time (see
# Containerfile.tls-gateway). The Redis server cert is mounted into the
# redis container at runtime (see docker-compose-tls-redis.yml).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${REPO_ROOT}/tls-certs"

mkdir -p "${CERT_DIR}"
cd "${CERT_DIR}"

# Local self-signed CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 \
    -subj "/CN=cpex-tls-test-ca" \
    -out ca.crt

# Redis server cert signed by the CA
openssl genrsa -out redis.key 2048
openssl req -new -key redis.key -subj "/CN=redis" -out redis.csr

cat > redis.ext <<'EOF'
subjectAltName = DNS:redis,DNS:redis-tls,DNS:localhost,IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF

openssl x509 -req -in redis.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out redis.crt -days 365 -sha256 \
    -extfile redis.ext

# Cleanup intermediates
rm -f redis.csr redis.ext ca.srl

# Permissions: CA + cert world-readable, keys 0600
chmod 0644 ca.crt redis.crt
chmod 0600 ca.key redis.key

echo
echo "Wrote certs to ${CERT_DIR}:"
ls -la "${CERT_DIR}"
