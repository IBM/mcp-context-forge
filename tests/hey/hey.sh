#!/usr/bin/env bash

# ==============================================================================
# A wrapper around the `hey` HTTP load testing tool.
#
# Features:
#   - Strict mode (`set -euo pipefail`) for safer scripting
#   - Dependency checks for required commands
#   - Flexible CLI arguments with sensible defaults
#   - Automatic validation of required parameters
#   - Help/usage message
#   - Clean logging with timestamps
#   - Dry-run mode to preview the command without executing
# ==============================================================================

set -Eeuo pipefail
IFS=$'\n\t'

#-------------------------------#
#   Default Configuration      #
#-------------------------------#
CONCURRENCY=200
REQUESTS=10000
METHOD="POST"
CONTENT_TYPE="application/json"
HEADERS=()
PAYLOAD_FILE="payload.json"
URL="http://localhost:4444/rpc"
DRY_RUN=false
LOG_FILE="hey-$(date +%Y%m%d_%H%M%S).log"

#-------------------------------#
#       Helper Functions        #
#-------------------------------#
usage() {
  cat <<EOF
Usage: ${0##*/} [options]

Options:
  -n <num>        Total number of requests (default: $REQUESTS)
  -c <num>        Number of concurrent workers (default: $CONCURRENCY)
  -X <method>     HTTP method (default: $METHOD)
  -T <type>       Content-Type header (default: $CONTENT_TYPE)
  -H <header>     Additional header (can be used multiple times)
  -d <file>       Payload JSON file (default: $PAYLOAD_FILE)
  -u <url>        Target URL (required)
  -l <file>       Log output to file (default: $LOG_FILE)
  --dry-run       Show the `hey` command without running it
  -h, --help      Display this help and exit

Example:
  ${0##*/} -n 5000 -c 100 \
    -X POST -T application/json \
    -H "Authorization: Bearer \$JWT" \
    -d payload.json \
    -u http://localhost:4444/rpc
EOF
  exit 1
}

log() {
  local ts
  ts="$(date +'%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $*" | tee -a "$LOG_FILE"
}

check_command() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERROR: Required command '$1' not found in PATH." >&2
    exit 2
  fi
}

#-------------------------------#
#     Parse Command-Line       #
#-------------------------------#
while (( "$#" )); do
  case "$1" in
    -n) REQUESTS="$2"; shift 2 ;;
    -c) CONCURRENCY="$2"; shift 2 ;;
    -X) METHOD="$2"; shift 2 ;;
    -T) CONTENT_TYPE="$2"; shift 2 ;;
    -H) HEADERS+=("$2"); shift 2 ;;
    -d) PAYLOAD_FILE="$2"; shift 2 ;;
    -u) URL="$2"; shift 2 ;;
    -l) LOG_FILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

#-------------------------------#
#   Validate Required Inputs   #
#-------------------------------#
[[ -z "$URL" ]] && { echo "ERROR: Target URL is required."; usage; }
[[ -f "$PAYLOAD_FILE" ]] || { echo "ERROR: Payload file '$PAYLOAD_FILE' not found."; exit 3; }

#-------------------------------#
#     Dependency Verification   #
#-------------------------------#
check_command hey
check_command date
check_command tee

#-------------------------------#
#      Build `hey` Command      #
#-------------------------------#
HEY_CMD=(
  hey
  -n "$REQUESTS"
  -c "$CONCURRENCY"
  -m "$METHOD"
  -T "$CONTENT_TYPE"
  -D "$PAYLOAD_FILE"
  -t 60
)

# Append each header
for hdr in "${HEADERS[@]}"; do
  HEY_CMD+=(-H "$hdr")
done

HEY_CMD+=("$URL")

#-------------------------------#
#      Execute or Dry-Run       #
#-------------------------------#
log "Invoking load test:"
log "  Requests:      $REQUESTS"
log "  Concurrency:   $CONCURRENCY"
log "  Method:        $METHOD"
log "  Content-Type:  $CONTENT_TYPE"
log "  Payload file:  $PAYLOAD_FILE"
log "  URL:           $URL"
[[ ${#HEADERS[@]} -gt 0 ]] && log "  Headers:       ${HEADERS[*]}"
log "  Log file:      $LOG_FILE"

if [ "$DRY_RUN" = true ]; then
  echo -e "\nDry-run mode: Here's the command that would be executed:\n"
  printf ' %q' "${HEY_CMD[@]}"
  echo
  exit 0
fi

# Run and capture output
"${HEY_CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

if [ "$EXIT_CODE" -ne 0 ]; then
  log "ERROR: 'hey' exited with code $EXIT_CODE."
  exit "$EXIT_CODE"
else
  log "Load test completed successfully."
fi
