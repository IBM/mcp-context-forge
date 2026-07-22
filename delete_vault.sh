#!/bin/bash
set -e

delete_recursive() {
  local path="$1"
  echo "Checking: ${path}"

  # List contents
  response=$(curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
    "${VAULT_ADDR}/v1/secret/metadata/${path}?list=true")

  # Check if there are keys
  keys=$(echo "$response" | jq -r '.data.keys[]?' 2>/dev/null)

  if [ -n "$keys" ]; then
    # Has children - recurse first
    while IFS= read -r key; do
      delete_recursive "${path}/${key%/}"
    done <<< "$keys"
  fi

  # Now delete this path
  echo "Deleting: ${path}"
  curl -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
    "${VAULT_ADDR}/v1/secret/metadata/${path}"
}

# Check required environment variables
if [ -z "$VAULT_TOKEN" ] || [ -z "$VAULT_ADDR" ]; then
  echo "Error: VAULT_TOKEN and VAULT_ADDR must be set"
  exit 1
fi

# Start deletion
echo "Starting recursive deletion of Vault secrets..."
delete_recursive "contextforge/oauth/f8927490a44d4ede95889136d004c202"

echo -e "\nDone! Verifying deletion..."
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true" \
  | jq '.data'
