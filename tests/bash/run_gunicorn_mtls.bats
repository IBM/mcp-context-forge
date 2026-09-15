#!/usr/bin/env bats
# Tests for the inbound mTLS wiring in run-gunicorn.sh (CA_CERTS / CERT_REQS and
# the loopback client-certificate variables).
#
# The launcher is driven with a stub `gunicorn` on PATH, so no server is started
# and no socket is opened. Assertions are made against the "Command:" line the
# script prints immediately before exec, plus the exit status and error text.
#
# This suite is self-contained: the helpers in test_helper/helpers.bash are
# git-fixture utilities for the secrets merge driver and do not apply here.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    TMP_DIR="$(mktemp -d)"

    # Stub gunicorn: answers the --no-control-socket capability probe, otherwise
    # echoes its arguments and exits cleanly.
    mkdir -p "${TMP_DIR}/bin"
    cat > "${TMP_DIR}/bin/gunicorn" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "--help" ]]; then
    echo "  --no-control-socket   stub"
    exit 0
fi
echo "STUB_GUNICORN_ARGS: $*"
exit 0
STUB
    chmod +x "${TMP_DIR}/bin/gunicorn"

    # A fake active virtualenv stops SECTION 3 from sourcing the repo's real
    # .venv, which would otherwise prepend its bin/ and shadow the stub.
    mkdir -p "${TMP_DIR}/venv/bin"
    ln -s "$(command -v python3)" "${TMP_DIR}/venv/bin/python"

    # Throwaway PEMs. The stub never parses them; only the launcher's -f/-r
    # checks look at them.
    printf 'not-a-real-cert\n' > "${TMP_DIR}/cert.pem"
    printf 'not-a-real-key\n' > "${TMP_DIR}/key.pem"
    printf 'not-a-real-ca\n' > "${TMP_DIR}/ca.pem"
    printf 'not-a-real-client-cert\n' > "${TMP_DIR}/client-cert.pem"
    printf 'not-a-real-client-key\n' > "${TMP_DIR}/client-key.pem"
}

teardown() {
    chmod -R u+rwX "${TMP_DIR}" 2>/dev/null || true
    rm -rf "${TMP_DIR}"
}

# Run the launcher with the stub environment. Extra env assignments are passed
# through the caller's environment.
run_launcher() {
    run env \
        PATH="${TMP_DIR}/bin:${PATH}" \
        VIRTUAL_ENV="${TMP_DIR}/venv" \
        LOCK_FILE="${TMP_DIR}/gunicorn.lock" \
        GUNICORN_WORKERS=2 \
        "$@" \
        "${REPO_ROOT}/run-gunicorn.sh"
}

tls_args() {
    echo "SSL=true" "CERT_FILE=${TMP_DIR}/cert.pem" "KEY_FILE=${TMP_DIR}/key.pem"
}

# --- Regression guards: unset behaviour is unchanged -------------------------

@test "no SSL and no mTLS vars: no client-cert flags are passed" {
    run_launcher
    [ "$status" -eq 0 ]
    [[ "$output" != *"--ca-certs"* ]]
    [[ "$output" != *"--cert-reqs"* ]]
}

@test "SSL only: server cert flags passed, no mTLS flags" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--certfile ${TMP_DIR}/cert.pem"* ]]
    [[ "$output" == *"--keyfile ${TMP_DIR}/key.pem"* ]]
    [[ "$output" != *"--ca-certs"* ]]
    [[ "$output" != *"--cert-reqs"* ]]
}

@test "SSL=false: CA_CERTS is not read, even when the path is bogus" {
    run_launcher SSL=false CA_CERTS=/nonexistent/ca.pem CERT_REQS=2
    [ "$status" -eq 0 ]
    [[ "$output" != *"--ca-certs"* ]]
    [[ "$output" != *"FATAL"* ]]
}

# --- Happy path --------------------------------------------------------------

@test "CA_CERTS with CERT_REQS=2 passes both flags to gunicorn" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=2 \
        LOOPBACK_CLIENT_CERT="${TMP_DIR}/client-cert.pem" \
        LOOPBACK_CLIENT_KEY="${TMP_DIR}/client-key.pem"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--ca-certs ${TMP_DIR}/ca.pem"* ]]
    [[ "$output" == *"--cert-reqs 2"* ]]
}

@test "CA_CERTS with CERT_REQS=0 still passes the flags but warns" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=0
    [ "$status" -eq 0 ]
    [[ "$output" == *"--cert-reqs 0"* ]]
    [[ "$output" == *"CERT_REQS=0"* ]]
    [[ "$output" == *"will NOT be requested"* ]]
}

# --- Fail-fast validation ----------------------------------------------------

@test "missing CA_CERTS file is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS=/nonexistent/ca.pem
    [ "$status" -eq 1 ]
    [[ "$output" == *"CA certificate bundle not found"* ]]
}

@test "unreadable CA_CERTS file is fatal" {
    if [ "$(id -u)" -eq 0 ]; then
        skip "root bypasses file permission checks"
    fi
    chmod 000 "${TMP_DIR}/ca.pem"
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Cannot read CA certificate bundle"* ]]
}

@test "out-of-range CERT_REQS is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=3
    [ "$status" -eq 1 ]
    [[ "$output" == *"CERT_REQS must be 0, 1, or 2"* ]]
}

@test "non-numeric CERT_REQS is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=required
    [ "$status" -eq 1 ]
    [[ "$output" == *"CERT_REQS must be 0, 1, or 2"* ]]
}

@test "CERT_REQS without CA_CERTS is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CERT_REQS=2
    [ "$status" -eq 1 ]
    [[ "$output" == *"requires CA_CERTS"* ]]
}

# --- Loopback client certificate ---------------------------------------------

@test "loopback cert without key is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=2 \
        LOOPBACK_CLIENT_CERT="${TMP_DIR}/client-cert.pem"
    [ "$status" -eq 1 ]
    [[ "$output" == *"must be set together"* ]]
}

@test "missing loopback credential file is fatal" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=2 \
        LOOPBACK_CLIENT_CERT=/nonexistent/client.pem \
        LOOPBACK_CLIENT_KEY="${TMP_DIR}/client-key.pem"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Loopback client credential not found"* ]]
}

@test "CERT_REQS=2 without loopback credentials warns about SSE and WebSocket" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=2
    [ "$status" -eq 0 ]
    [[ "$output" == *"SSE and WebSocket transports will fail"* ]]
}

@test "CERT_REQS=1 without loopback credentials does not warn" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        CA_CERTS="${TMP_DIR}/ca.pem" CERT_REQS=1
    [ "$status" -eq 0 ]
    [[ "$output" != *"SSE and WebSocket transports will fail"* ]]
}

@test "unreadable LOOPBACK_CLIENT_CERT is fatal even without CA_CERTS/CERT_REQS" {
    if [ "$(id -u)" -eq 0 ]; then
        skip "root bypasses file permission checks"
    fi
    chmod 000 "${TMP_DIR}/client-cert.pem"
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        LOOPBACK_CLIENT_CERT="${TMP_DIR}/client-cert.pem" \
        LOOPBACK_CLIENT_KEY="${TMP_DIR}/client-key.pem"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Cannot read loopback client credential"* ]]
}

@test "missing loopback credential file is fatal even without CA_CERTS/CERT_REQS" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        LOOPBACK_CLIENT_CERT=/nonexistent/client.pem \
        LOOPBACK_CLIENT_KEY="${TMP_DIR}/client-key.pem"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Loopback client credential not found"* ]]
}

# --- TLS Cipher Suites and Protocol Version ----------------------------------

@test "SSL_CIPHERS passes --ciphers flag to gunicorn when SSL=true" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        SSL_CIPHERS="ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--ciphers ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256"* ]]
}

@test "SSL_VERSION passes --ssl-version flag to gunicorn when SSL=true" {
    run_launcher SSL=true CERT_FILE="${TMP_DIR}/cert.pem" KEY_FILE="${TMP_DIR}/key.pem" \
        SSL_VERSION="5"
    [ "$status" -eq 0 ]
    [[ "$output" == *"--ssl-version 5"* ]]
}

@test "SSL_CIPHERS and SSL_VERSION are ignored when SSL=false" {
    run_launcher SSL=false \
        SSL_CIPHERS="ECDHE-RSA-AES256-GCM-SHA384" \
        SSL_VERSION="5"
    [ "$status" -eq 0 ]
    [[ "$output" != *"--ciphers"* ]]
    [[ "$output" != *"--ssl-version"* ]]
}
