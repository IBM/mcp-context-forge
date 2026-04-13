#!/bin/bash
set -e

# ─────────────────────────────────────────────
# Usage: ./setup-nfs-provisioner.sh [OPTIONS]
#
# Options (all optional — you'll be prompted for any that are missing):
#   --nfs-server      IP or hostname of the NFS server
#   --nfs-path        Export path on the NFS server
#   --ssh-user        SSH user for the NFS server
#   --namespace       OpenShift namespace for the provisioner
#   --storage-class   Name of the StorageClass to create
#   --default-class   Set as default StorageClass? (true/false)
#
# Example:
#   ./setup-nfs-provisioner.sh \
#     --nfs-server 9.x.x.x \
#     --nfs-path /data/dynamic-storage \
#     --ssh-user admin \
#     --namespace nfs-provisioner \
#     --storage-class nfs-client \
#     --default-class false
# ─────────────────────────────────────────────

# ── Parse named arguments ──────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --nfs-server)    NFS_SERVER="$2";    shift 2 ;;
    --nfs-path)      NFS_PATH="$2";      shift 2 ;;
    --ssh-user)      SSH_USER="$2";      shift 2 ;;
    --namespace)     NAMESPACE="$2";     shift 2 ;;
    --storage-class) STORAGE_CLASS="$2"; shift 2 ;;
    --default-class) DEFAULT_CLASS="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Prompt for any missing values ──────────────────────────────────────────────
prompt() {
  local var_name="$1"
  local prompt_text="$2"
  local default="$3"

  if [[ -z "${!var_name}" ]]; then
    if [[ -n "$default" ]]; then
      read -rp "$prompt_text [$default]: " input
      eval "$var_name=\"${input:-$default}\""
    else
      read -rp "$prompt_text: " input
      eval "$var_name=\"$input\""
    fi
  fi
}

prompt NFS_SERVER    "NFS server IP or hostname"          ""
prompt NFS_PATH      "NFS export path"                    "/data/dynamic-storage"
prompt SSH_USER      "SSH user for NFS server"            "root"
prompt NAMESPACE     "OpenShift namespace"                "nfs-provisioner"
prompt STORAGE_CLASS "StorageClass name"                  "nfs-client"
prompt DEFAULT_CLASS "Set as default StorageClass? (true/false)" "false"

# ── Summary before proceeding ──────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────"
echo "  NFS Server    : $NFS_SERVER"
echo "  NFS Path      : $NFS_PATH"
echo "  SSH User      : $SSH_USER"
echo "  Namespace     : $NAMESPACE"
echo "  StorageClass  : $STORAGE_CLASS"
echo "  Default Class : $DEFAULT_CLASS"
echo "──────────────────────────────────────────"
read -rp "Proceed? (y/N): " confirm
[[ "$(echo "$confirm" | tr '[:upper:]' '[:lower:]')" == "y" ]] || { echo "Aborted."; exit 0; }

# ── 1. Configure NFS server ────────────────────────────────────────────────────
echo ""
echo "===> Setting up NFS server"

ssh "${SSH_USER}@${NFS_SERVER}" bash <<EOF
  set -e
  sudo mkdir -p "${NFS_PATH}"
  sudo chmod 777 "${NFS_PATH}"

  if ! grep -q "${NFS_PATH}" /etc/exports; then
    echo "${NFS_PATH} *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
  else
    echo "Export entry already exists, skipping."
  fi

  sudo exportfs -ra
  sudo exportfs -v
EOF

# ── 2. Create namespace ────────────────────────────────────────────────────────
echo ""
echo "===> Creating namespace: $NAMESPACE"
oc create namespace "$NAMESPACE" || true

# ── 3. Configure Security Context Constraints (SCC) for OpenShift ─────────────
echo ""
echo "===> Configuring OpenShift Security Context Constraints"
# The NFS provisioner needs hostmount-anyuid SCC to mount NFS volumes
oc adm policy add-scc-to-user hostmount-anyuid \
  system:serviceaccount:"$NAMESPACE":nfs-provisioner-nfs-subdir-external-provisioner \
  2>/dev/null || echo "SCC already configured or will be set after Helm install"

# ── 4. Install NFS provisioner via Helm ───────────────────────────────────────
echo ""
echo "===> Installing NFS provisioner"

helm repo add nfs-subdir-external-provisioner \
  https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner 2>/dev/null || true
helm repo update

helm upgrade --install nfs-provisioner \
  nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
  --namespace "$NAMESPACE" \
  --set nfs.server="$NFS_SERVER" \
  --set nfs.path="$NFS_PATH" \
  --set storageClass.name="$STORAGE_CLASS" \
  --set storageClass.defaultClass="$DEFAULT_CLASS"

# ── 4. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "===> Verifying"
oc get pods -n "$NAMESPACE"
oc get storageclass

echo ""
echo "Done"
