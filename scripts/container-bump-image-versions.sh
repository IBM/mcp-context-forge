#!/usr/bin/env bash
# container-bump-image-versions.sh — bump pinned Red Hat UBI image tags in the
# repo's Containerfiles to the latest build tag within their CURRENT minor line.
#
# Managed pins (full build tags only, e.g. 10.2-1784669047):
#   Containerfile:               ARG UBI_BASE / NODEJS_IMAGE / UBI_MINIMAL
#   infra/wheels/Containerfile:  ARG UBI_MINIMAL (must stay identical to root)
#   infra/nginx/Dockerfile:      ARG NGINX_IMAGE
#
# Tags are discovered via the Red Hat Catalog (Pyxis) API, which allows
# anonymous access:
#   GET https://catalog.redhat.com/api/containers/v1/repositories/registry/
#       registry.access.redhat.com/repository/<repo>/images
#       ?page_size=500&sort_by=last_update_date[desc]
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
#   - The wheels UBI_MINIMAL pin is validated (present and identical to the
#     root pin) before any write; a missing or divergent pin aborts the run.
#   - Both UBI_MINIMAL pins are always updated together.
#
# Requires: bash 3.2+, curl, jq.
# Test hooks: CONTAINERFILE_PATH / WHEELS_CONTAINERFILE_PATH /
#             NGINX_DOCKERFILE_PATH override the file locations
#             (used by tests/scripts/container-bump-image-versions.bats).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONTAINERFILE_PATH="${CONTAINERFILE_PATH:-$REPO_ROOT/Containerfile}"
WHEELS_CONTAINERFILE_PATH="${WHEELS_CONTAINERFILE_PATH:-$REPO_ROOT/infra/wheels/Containerfile}"
NGINX_DOCKERFILE_PATH="${NGINX_DOCKERFILE_PATH:-$REPO_ROOT/infra/nginx/Dockerfile}"

PYXIS_BASE="https://catalog.redhat.com/api/containers/v1/repositories/registry/registry.access.redhat.com/repository"

# Managed ARG names, in order.  Each entry has a corresponding entry at the
# same index in MANAGED_FILES (the file that owns the ARG).
MANAGED_ARGS=(UBI_BASE NODEJS_IMAGE UBI_MINIMAL NGINX_IMAGE)
MANAGED_FILES=("$CONTAINERFILE_PATH" "$CONTAINERFILE_PATH" "$CONTAINERFILE_PATH" "$NGINX_DOCKERFILE_PATH")

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
        "${PYXIS_BASE}/${repo}/images?page_size=500&sort_by=last_update_date[desc]" \
        | jq -r '[.data[]?.repositories[]?.tags[]?.name] | unique | .[]'
}

die() { echo "ERROR: $*" >&2; exit 1; }

main() {
    command -v curl >/dev/null || die "curl is required"
    command -v jq   >/dev/null || die "jq is required"
    [ -f "$CONTAINERFILE_PATH" ]        || die "not found: $CONTAINERFILE_PATH"
    [ -f "$WHEELS_CONTAINERFILE_PATH" ] || die "not found: $WHEELS_CONTAINERFILE_PATH"
    [ -f "$NGINX_DOCKERFILE_PATH" ]     || die "not found: $NGINX_DOCKERFILE_PATH"

    # Parallel arrays used in place of associative arrays (bash 3.2 compat).
    # Indices align with MANAGED_ARGS.
    local cur_tags=()   # current tag for each ARG
    local new_tags=()   # new tag (empty string = up to date)
    local image_refs=() # image ref (without tag) for each ARG

    # ---- Plan phase: validate pins and resolve latest tags; no writes ----
    local arg src_file line value tag minor image repo tags latest i
    for i in "${!MANAGED_ARGS[@]}"; do
        arg="${MANAGED_ARGS[$i]}"
        src_file="${MANAGED_FILES[$i]}"
        line=$(grep -E "^ARG ${arg}=" "$src_file") \
            || die "no '^ARG ${arg}=' line in $src_file"
        value="${line#ARG "${arg}"=}"
        tag="${value##*:}"
        [[ "$tag" =~ ^[0-9]+\.[0-9]+-[0-9]+$ ]] \
            || die "${arg} pin '${value}' is not a full build tag (<minor>-<epoch>); refusing to manage it"
        minor="${tag%-*}"

        image="${value%:*}"
        [[ "$image" == registry.access.redhat.com/* ]] \
            || die "${arg} image '${image}' is not on registry.access.redhat.com; Pyxis lookup is only defined for that registry"
        repo="${image#registry.access.redhat.com/}"

        # UBI_MINIMAL must be pinned identically in the wheels Containerfile.
        # Validate it now: sed no-ops (exit 0) on a missing match, so without
        # this check apply would report success while the pins silently diverge.
        if [ "$arg" = "UBI_MINIMAL" ]; then
            local wheels_line wheels_value
            wheels_line=$(grep -E "^ARG ${arg}=" "$WHEELS_CONTAINERFILE_PATH") \
                || die "no '^ARG ${arg}=' line in $WHEELS_CONTAINERFILE_PATH; both UBI_MINIMAL pins must exist"
            wheels_value="${wheels_line#ARG "${arg}"=}"
            [ "$wheels_value" = "$value" ] \
                || die "UBI_MINIMAL pins differ between the Containerfiles ('${value}' vs '${wheels_value}'); reconcile them before bumping"
        fi

        tags=$(fetch_tags "$repo") \
            || die "tag lookup failed for ${arg} (${repo}); no files modified"
        latest=$(printf '%s\n' "$tags" | latest_tag_in_minor "$minor") \
            || die "no pinned tag in minor line ${minor} found for ${arg}; no files modified"

        cur_tags[$i]="$tag"
        image_refs[$i]="$image"
        if [ "$latest" != "$tag" ]; then
            new_tags[$i]="$latest"
        else
            new_tags[$i]=""
        fi
    done

    # ---- Report ----
    local any_update=0
    for i in "${!MANAGED_ARGS[@]}"; do
        arg="${MANAGED_ARGS[$i]}"
        if [ -n "${new_tags[$i]}" ]; then
            echo "${arg}: ${cur_tags[$i]} -> ${new_tags[$i]}"
            any_update=1
        else
            echo "${arg}: ${cur_tags[$i]} (up to date)"
        fi
    done

    if [ "$any_update" -eq 0 ]; then
        echo "All image pins are up to date."
        return 0
    fi

    # ---- Apply phase ----
    # Write all files under a commit-or-rollback discipline:
    #   - sed -i.bak creates one backup per file before touching it.
    #   - If the loop completes without error, ok=1 and EXIT removes the backups.
    #   - If any write fails, ok stays 0 and EXIT restores every backup that
    #     was created, leaving the repo in its original state.
    _bump_ok=0
    trap 'for f in "${CONTAINERFILE_PATH}" "${WHEELS_CONTAINERFILE_PATH}" "${NGINX_DOCKERFILE_PATH}"; do
              [ -e "${f}.bak" ] || continue
              if [ "${_bump_ok:-0}" = 1 ]; then rm -f "${f}.bak"; else mv -f "${f}.bak" "$f"; fi
          done' EXIT
    for i in "${!MANAGED_ARGS[@]}"; do
        [ -n "${new_tags[$i]}" ] || continue
        arg="${MANAGED_ARGS[$i]}"
        local files=("${MANAGED_FILES[$i]}")
        # UBI_MINIMAL is pinned in both Containerfiles; keep them identical.
        if [ "$arg" = "UBI_MINIMAL" ]; then
            files+=("$WHEELS_CONTAINERFILE_PATH")
        fi
        local f
        for f in "${files[@]}"; do
            sed -i.bak "s|^ARG ${arg}=.*|ARG ${arg}=${image_refs[$i]}:${new_tags[$i]}|" "$f" \
                || die "failed to update ${arg} in $f"
            echo "  updated $f"
        done
    done
    _bump_ok=1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
