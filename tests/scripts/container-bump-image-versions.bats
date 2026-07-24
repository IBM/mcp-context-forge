#!/usr/bin/env bats
# Tests for scripts/container-bump-image-versions.sh
#
# Strategy: stub `curl` on PATH to serve canned Pyxis API responses, run the
# script against throwaway Containerfile fixtures, and assert on file contents.
# The script must never partially write: any fetch/parse failure means zero
# files modified.

SCRIPT="$BATS_TEST_DIRNAME/../../scripts/container-bump-image-versions.sh"

setup() {
    TEST_DIR="$(mktemp -d)"
    FIXTURE_DIR="$TEST_DIR/api"
    mkdir -p "$FIXTURE_DIR" "$TEST_DIR/bin"

    # Containerfile fixtures mirroring the real pin lines.
    cat > "$TEST_DIR/Containerfile" <<'EOF'
# Base image overrides — defaults to UBI 10; pass UBI 9 values for FedRAMP builds
ARG UBI_BASE=registry.access.redhat.com/ubi10:10.2-1784581466
ARG NODEJS_IMAGE=registry.access.redhat.com/ubi10/nodejs-24:10.2-1784624696
ARG UBI_MINIMAL=registry.access.redhat.com/ubi10/ubi-minimal:10.2-1784581369
FROM ${UBI_BASE}
EOF
    cat > "$TEST_DIR/wheels.Containerfile" <<'EOF'
ARG UBI_MINIMAL=registry.access.redhat.com/ubi10/ubi-minimal:10.2-1784581369
FROM ${UBI_MINIMAL}
EOF
    cp "$TEST_DIR/Containerfile" "$TEST_DIR/Containerfile.orig"
    cp "$TEST_DIR/wheels.Containerfile" "$TEST_DIR/wheels.Containerfile.orig"

    # curl stub: dispatch on the repository path embedded in the Pyxis URL.
    # More specific paths first; unknown URLs fail like a 404 (curl -f style).
    # Emulates curl's URL-globbing behavior: a literal '[' in the URL fails
    # with exit 3 unless globbing is disabled (-g / --globoff).
    cat > "$TEST_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
case " $* " in
    *" -g "*|*" --globoff "*) ;;
    *) case "$*" in *\[*) echo "curl: (3) bad range in URL" >&2; exit 3 ;; esac ;;
esac
case "$*" in
    *repository/ubi10/ubi-minimal/images*) cat "$FIXTURE_DIR/ubi-minimal.json" ;;
    *repository/ubi10/nodejs-24/images*)   cat "$FIXTURE_DIR/nodejs.json" ;;
    *repository/ubi10/images*)             cat "$FIXTURE_DIR/ubi10.json" ;;
    *) echo "stub curl: unstubbed URL: $*" >&2; exit 22 ;;
esac
EOF
    chmod +x "$TEST_DIR/bin/curl"
    export PATH="$TEST_DIR/bin:$PATH"
    export FIXTURE_DIR
    export CONTAINERFILE_PATH="$TEST_DIR/Containerfile"
    export WHEELS_CONTAINERFILE_PATH="$TEST_DIR/wheels.Containerfile"
}

teardown() {
    rm -rf "$TEST_DIR"
}

# Helper: write a Pyxis-style response listing the given tag names.
write_tags() {  # write_tags <fixture-name> <tag>...
    local file="$FIXTURE_DIR/$1"; shift
    local tags=""
    local t
    for t in "$@"; do
        tags+="{\"name\": \"$t\"},"
    done
    printf '{"data": [{"repositories": [{"tags": [%s]}]}]}' "${tags%,}" > "$file"
}

# --- Unit: latest_tag_in_minor ------------------------------------------------

@test "latest_tag_in_minor picks highest epoch within the minor line" {
    run bash -c "source '$SCRIPT'; printf '%s\n' '10.2-100' '10.2-1784669047' '10.2-1784581369' | latest_tag_in_minor 10.2"
    [ "$status" -eq 0 ]
    [ "$output" = "10.2-1784669047" ]
}

@test "latest_tag_in_minor ignores other minor lines and floating tags" {
    run bash -c "source '$SCRIPT'; printf '%s\n' '10.3-9999999999' '10.2' 'latest' '10.2-1784669047' '10.1-9999999999' | latest_tag_in_minor 10.2"
    [ "$status" -eq 0 ]
    [ "$output" = "10.2-1784669047" ]
}

@test "latest_tag_in_minor fails when no matching pinned tag exists" {
    run bash -c "source '$SCRIPT'; printf '%s\n' 'latest' '10.2' '10.3-1784669047' | latest_tag_in_minor 10.2"
    [ "$status" -eq 1 ]
}

# --- Integration: bump behavior ------------------------------------------------

@test "updates all three ARGs in root Containerfile when newer tags exist" {
    write_tags ubi10.json        "10.2-1784669000" "10.2-1784581466" "latest"
    write_tags nodejs.json       "10.2-1784669001" "10.2"
    write_tags ubi-minimal.json  "10.2-1784669047" "10.2-1784581369"

    run "$SCRIPT"
    [ "$status" -eq 0 ]

    run grep '^ARG UBI_BASE=' "$CONTAINERFILE_PATH"
    [ "$output" = "ARG UBI_BASE=registry.access.redhat.com/ubi10:10.2-1784669000" ]
    run grep '^ARG NODEJS_IMAGE=' "$CONTAINERFILE_PATH"
    [ "$output" = "ARG NODEJS_IMAGE=registry.access.redhat.com/ubi10/nodejs-24:10.2-1784669001" ]
    run grep '^ARG UBI_MINIMAL=' "$CONTAINERFILE_PATH"
    [ "$output" = "ARG UBI_MINIMAL=registry.access.redhat.com/ubi10/ubi-minimal:10.2-1784669047" ]
}

@test "updates UBI_MINIMAL pin in the wheels Containerfile too" {
    write_tags ubi10.json        "10.2-1784581466"
    write_tags nodejs.json       "10.2-1784624696"
    write_tags ubi-minimal.json  "10.2-1784669047"

    run "$SCRIPT"
    [ "$status" -eq 0 ]

    run grep '^ARG UBI_MINIMAL=' "$WHEELS_CONTAINERFILE_PATH"
    [ "$output" = "ARG UBI_MINIMAL=registry.access.redhat.com/ubi10/ubi-minimal:10.2-1784669047" ]
}

@test "keeps both UBI_MINIMAL pins identical after update" {
    write_tags ubi10.json        "10.2-1784581466"
    write_tags nodejs.json       "10.2-1784624696"
    write_tags ubi-minimal.json  "10.2-1784669047"

    run "$SCRIPT"
    [ "$status" -eq 0 ]

    root_pin=$(grep '^ARG UBI_MINIMAL=' "$CONTAINERFILE_PATH")
    wheels_pin=$(grep '^ARG UBI_MINIMAL=' "$WHEELS_CONTAINERFILE_PATH")
    [ "$root_pin" = "$wheels_pin" ]
}

@test "no-op when every pin is already the latest in its minor line" {
    write_tags ubi10.json        "10.2-1784581466" "10.2-1000"
    write_tags nodejs.json       "10.2-1784624696" "10.2"
    write_tags ubi-minimal.json  "10.2-1784581369" "latest"

    run "$SCRIPT"
    [ "$status" -eq 0 ]
    [[ "$output" == *"up to date"* ]]
    cmp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    cmp "$WHEELS_CONTAINERFILE_PATH" "$TEST_DIR/wheels.Containerfile.orig"
}

@test "stays within the current minor line even when a newer minor exists" {
    write_tags ubi10.json        "10.3-9999999999" "10.2-1784581466"
    write_tags nodejs.json       "10.3-9999999999" "10.2-1784624696"
    write_tags ubi-minimal.json  "10.3-9999999999" "10.2-1784581369"

    run "$SCRIPT"
    [ "$status" -eq 0 ]
    cmp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    cmp "$WHEELS_CONTAINERFILE_PATH" "$TEST_DIR/wheels.Containerfile.orig"
}

@test "writes nothing when any repository lookup fails" {
    write_tags ubi10.json        "10.2-1784669000"
    write_tags nodejs.json       "10.2-1784669001"
    # ubi-minimal.json deliberately missing -> stub curl exits 22

    run "$SCRIPT"
    [ "$status" -eq 1 ]
    cmp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    cmp "$WHEELS_CONTAINERFILE_PATH" "$TEST_DIR/wheels.Containerfile.orig"
}

@test "writes nothing when the API returns malformed JSON" {
    write_tags ubi10.json        "10.2-1784669000"
    write_tags nodejs.json       "10.2-1784669001"
    echo "not json" > "$FIXTURE_DIR/ubi-minimal.json"

    run "$SCRIPT"
    [ "$status" -eq 1 ]
    cmp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    cmp "$WHEELS_CONTAINERFILE_PATH" "$TEST_DIR/wheels.Containerfile.orig"
}

@test "refuses to manage a pin that is not a full build tag" {
    sed -i '' 's|^ARG UBI_BASE=.*|ARG UBI_BASE=registry.access.redhat.com/ubi10:latest|' "$CONTAINERFILE_PATH"
    cp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    write_tags ubi10.json        "10.2-1784669000"
    write_tags nodejs.json       "10.2-1784624696"
    write_tags ubi-minimal.json  "10.2-1784581369"

    run "$SCRIPT"
    [ "$status" -eq 1 ]
    cmp "$CONTAINERFILE_PATH" "$TEST_DIR/Containerfile.orig"
    cmp "$WHEELS_CONTAINERFILE_PATH" "$TEST_DIR/wheels.Containerfile.orig"
}
