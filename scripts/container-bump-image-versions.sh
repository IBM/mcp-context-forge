#!/usr/bin/env bash
# container-bump-image-versions.sh — bump pinned Red Hat UBI image tags in the
# repo's Containerfiles to the latest build tag within their CURRENT minor line.
#
# Managed pins (full build tags only, e.g. 10.2-1784669047):
#   Containerfile:               ARG UBI_BASE / NODEJS_IMAGE / UBI_MINIMAL
#   infra/wheels/Containerfile:  ARG UBI_MINIMAL (must stay identical to root)
#
# Tags are discovered via the Red Hat Catalog (Pyxis) API, which allows
# anonymous access:
#   GET https://catalog.redhat.com/api/containers/v1/repositories/registry/
#       registry.access.redhat.com/repository/<repo>/images
#       ?page_size=100&sort_by=last_update_date[desc]
#
# Policy:
#   - Stay within each pin's current minor line (10.2); minor bumps are a
#     deliberate, reviewed change — not something a script should do.
#   - The ENABLE_FIPS build path overrides these ARGs with UBI 9 images at
#     build time (see Makefile container-build); those are not file-pinned
#     and are intentionally not managed here.
#
# Safety:
#   - All lookups and validation complete before any file is written; a
#     failed or malformed API response means zero files modified.
#   - Both UBI_MINIMAL pins are always updated together.
#
# Requires: curl, jq.
# Test hooks: CONTAINERFILE_PATH / WHEELS_CONTAINERFILE_PATH override the
# file locations (used by tests/scripts/container-bump-image-versions.bats).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONTAINERFILE_PATH="${CONTAINERFILE_PATH:-$REPO_ROOT/Containerfile}"
WHEELS_CONTAINERFILE_PATH="${WHEELS_CONTAINERFILE_PATH:-$REPO_ROOT/infra/wheels/Containerfile}"

PYXIS_BASE="https://catalog.redhat.com/api/containers/v1/repositories/registry/registry.access.redhat.com/repository"

# The Pyxis repository path is derived from each pin's image reference
# (${value%:*} minus the registry prefix), so a deliberate image-path change
# in a Containerfile cannot drift from the queried endpoint.
MANAGED_ARGS=(UBI_BASE NODEJS_IMAGE UBI_MINIMAL)

# latest_tag_in_minor <minor> — read candidate tags (one per line) on stdin,
# print the tag matching ^<minor>-<epoch>$ with the numerically highest epoch.
# Exit 1 when no such tag exists.
latest_tag_in_minor() {
    local minor="$1" esc best
    esc="${minor//./\\.}"
    best=$(grep -E "^${esc}-[0-9]+$" | sort -t- -k2,2 -n | tail -n1) || return 1
    [ -n "$best" ] || return 1
    printf '%s\n' "$best"
}

# fetch_tags <repo> — print all tag names reported by the Pyxis API.
fetch_tags() {
    local repo="$1"
    curl -fsSL -g --retry 3 --retry-delay 2 \
        "${PYXIS_BASE}/${repo}/images?page_size=100&sort_by=last_update_date[desc]" \
        | jq -r '[.data[]?.repositories[]?.tags[]?.name] | unique | .[]'
}

die() { echo "ERROR: $*" >&2; exit 1; }

main() {
    command -v curl >/dev/null || die "curl is required"
    command -v jq   >/dev/null || die "jq is required"
    [ -f "$CONTAINERFILE_PATH" ]        || die "not found: $CONTAINERFILE_PATH"
    [ -f "$WHEELS_CONTAINERFILE_PATH" ] || die "not found: $WHEELS_CONTAINERFILE_PATH"

    # ---- Plan phase: validate pins and resolve latest tags; no writes ----
    local arg line value tag minor image repo tags latest
    declare -A new_tag=()
    declare -A cur_tag=()
    declare -A image_of=()

    for arg in "${MANAGED_ARGS[@]}"; do
        line=$(grep -E "^ARG ${arg}=" "$CONTAINERFILE_PATH") \
            || die "no '^ARG ${arg}=' line in $CONTAINERFILE_PATH"
        value="${line#ARG "${arg}"=}"
        tag="${value##*:}"
        [[ "$tag" =~ ^[0-9]+\.[0-9]+-[0-9]+$ ]] \
            || die "${arg} pin '${value}' is not a full build tag (<minor>-<epoch>); refusing to manage it"
        minor="${tag%-*}"

        image="${value%:*}"
        [[ "$image" == registry.access.redhat.com/* ]] \
            || die "${arg} image '${image}' is not on registry.access.redhat.com; Pyxis lookup is only defined for that registry"
        repo="${image#registry.access.redhat.com/}"

        tags=$(fetch_tags "$repo") \
            || die "tag lookup failed for ${arg} (${repo}); no files modified"
        latest=$(printf '%s\n' "$tags" | latest_tag_in_minor "$minor") \
            || die "no pinned tag in minor line ${minor} found for ${arg}; no files modified"

        cur_tag[$arg]="$tag"
        image_of[$arg]="$image"
        if [ "$latest" != "$tag" ]; then
            new_tag[$arg]="$latest"
        fi
    done

    # ---- Report ----
    for arg in "${MANAGED_ARGS[@]}"; do
        if [ -n "${new_tag[$arg]:-}" ]; then
            echo "${arg}: ${cur_tag[$arg]} -> ${new_tag[$arg]}"
        else
            echo "${arg}: ${cur_tag[$arg]} (up to date)"
        fi
    done

    if [ "${#new_tag[@]}" -eq 0 ]; then
        echo "All image pins are up to date."
        return 0
    fi

    # ---- Apply phase ----
    for arg in "${!new_tag[@]}"; do
        local files=("$CONTAINERFILE_PATH")
        # UBI_MINIMAL is pinned in both Containerfiles; keep them identical.
        if [ "$arg" = "UBI_MINIMAL" ]; then
            files+=("$WHEELS_CONTAINERFILE_PATH")
        fi
        local f
        for f in "${files[@]}"; do
            if sed -i.bak "s|^ARG ${arg}=.*|ARG ${arg}=${image_of[$arg]}:${new_tag[$arg]}|" "$f"; then
                rm -f "${f}.bak"
            else
                die "failed to update ${arg} in $f"
            fi
            echo "  updated $f"
        done
    done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
