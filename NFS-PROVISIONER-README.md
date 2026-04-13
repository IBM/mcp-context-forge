# NFS Dynamic Provisioner Setup for OpenShift

Automated setup script for deploying NFS dynamic storage provisioners on OpenShift clusters.

## Overview

This script automates the complete setup of NFS-based dynamic storage provisioning in OpenShift, including:
- NFS server configuration
- OpenShift namespace creation
- Security Context Constraints (SCC) configuration
- Helm chart deployment for NFS provisioner
- StorageClass creation

## Prerequisites

- `oc` CLI installed and logged into your OpenShift cluster
- `helm` v3+ installed
- SSH access to the NFS server (infrastructure node)
- Root or sudo access on the NFS server
- Need infra node public IP

## Quick Start

### Single Provisioner Setup

```bash
# Make the script executable
chmod +x setup-nfs-provisioner.sh

# Run the script
./setup-nfs-provisioner.sh \
  --nfs-server x.x.x.x \
  --nfs-path /data/dynamic-storage \
  --ssh-user root \
  --namespace nfs-provisioner \
  --storage-class nfs-client \
  --default-class true
```

### Interactive Mode

Run without parameters to be prompted for each value:

```bash
./setup-nfs-provisioner.sh
```

## Multiple Provisioners

You can run multiple NFS provisioners in the same cluster for different storage tiers or purposes.

### Example: Two Provisioners

**Primary Storage (default):**
```bash
./setup-nfs-provisioner.sh \
  --nfs-server 9.60.245.8 \
  --nfs-path /data/dynamic-storage \
  --ssh-user root \
  --namespace nfs-provisioner \
  --storage-class nfs-client \
  --default-class true
```

If necessary:
**Secondary Storage:**
```bash
./setup-nfs-provisioner.sh \
  --nfs-server 9.60.245.8 \
  --nfs-path /data/dynamic-storage-2 \
  --ssh-user root \
  --namespace nfs-provisioner-2 \
  --storage-class nfs-client-2 \
  --default-class false
```

### Requirements for Multiple Provisioners

Each provisioner must have unique:
- `--namespace` (e.g., `nfs-provisioner-2`)
- `--storage-class` (e.g., `nfs-client-2`)
- `--nfs-path` (e.g., `/data/dynamic-storage-2`)

## Parameters

| Parameter | Description | Default | Required |
|-----------|-------------|---------|----------|
| `--nfs-server` | IP or hostname of NFS server | - | Yes |
| `--nfs-path` | Export path on NFS server | `/data/dynamic-storage` | No |
| `--ssh-user` | SSH user for NFS server | `admin` | No |
| `--namespace` | OpenShift namespace | `nfs-provisioner` | No |
| `--storage-class` | StorageClass name | `nfs-client` | No |
| `--default-class` | Set as default StorageClass | `false` | No |

## What the Script Does

1. **Configures NFS Server**
   - Creates export directory
   - Sets permissions (777)
   - Adds export to `/etc/exports`
   - Reloads NFS exports

2. **Creates OpenShift Resources**
   - Creates namespace
   - Configures Security Context Constraints (SCC)
   - Grants `hostmount-anyuid` permissions

3. **Deploys NFS Provisioner**
   - Adds Helm repository
   - Installs NFS subdir external provisioner
   - Creates StorageClass

4. **Verifies Installation**
   - Shows running pods
   - Lists StorageClasses

## Verification

### Check Provisioner Pod

```bash
oc get pods -n nfs-provisioner
```

Expected output:
```
NAME                                                              READY   STATUS    RESTARTS   AGE
nfs-provisioner-nfs-subdir-external-provisioner-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
```

### Check StorageClass

```bash
oc get storageclass
```

Expected output:
```
NAME                   PROVISIONER                                                     RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
nfs-client (default)   cluster.local/nfs-provisioner-nfs-subdir-external-provisioner   Delete          Immediate           true                   5m
```

### Test with a PVC

```bash
cat <<EOF | oc apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
  namespace: nfs-provisioner
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: 1Gi
EOF
```

Check PVC status:
```bash
oc get pvc -n nfs-provisioner
```

Expected: `test-pvc` should show `STATUS: Bound`

Clean up:
```bash
oc delete pvc test-pvc -n nfs-provisioner
```

## Troubleshooting

### Pod Not Starting

Check pod events:
```bash
oc describe pod -n nfs-provisioner -l app=nfs-subdir-external-provisioner
```

### SCC Issues

If you see "unable to validate against any security context constraint" errors:
```bash
oc adm policy add-scc-to-user hostmount-anyuid \
  system:serviceaccount:nfs-provisioner:nfs-provisioner-nfs-subdir-external-provisioner
```

Then restart the deployment:
```bash
oc rollout restart deployment/nfs-provisioner-nfs-subdir-external-provisioner -n nfs-provisioner
```

### PVC Stuck in Pending

Check provisioner logs:
```bash
oc logs -n nfs-provisioner -l app=nfs-subdir-external-provisioner
```

Verify NFS server connectivity from a pod:
```bash
oc run -it --rm debug --image=busybox --restart=Never -- sh
# Inside the pod:
ping 'infra node public ip'
```

### NFS Mount Issues

Verify NFS exports on the server:
```bash
ssh root@x.x.x.x "exportfs -v"
```

Check if directory exists and has correct permissions:
```bash
ssh root@x.x.x.x "ls -la /data/dynamic-storage"
```

## Cleanup

### Remove a Provisioner

```bash
# Delete the namespace (removes all resources)
oc delete namespace nfs-provisioner

# Clean up NFS export on the server
ssh root@x.x.x.x << 'EOF'
sudo sed -i '/\/data\/dynamic-storage/d' /etc/exports
sudo exportfs -ra
sudo rm -rf /data/dynamic-storage
EOF

# Remove Helm repo (optional)
helm repo remove nfs-subdir-external-provisioner
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ OpenShift Cluster                                           │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Namespace: nfs-provisioner                           │  │
│  │                                                      │  │
│  │  ┌────────────────────────────────────────────────┐ │  │
│  │  │ NFS Provisioner Pod                            │ │  │
│  │  │ - Watches for PVC creation                     │ │  │
│  │  │ - Creates PV dynamically                       │ │  │
│  │  │ - Mounts NFS share                             │ │  │
│  │  └────────────────────────────────────────────────┘ │  │
│  │                                                      │  │
│  │  StorageClass: nfs-client                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  Application Pods ──> PVC ──> PV ──> NFS Mount             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ NFS Protocol
                              ↓
                    ┌──────────────────────┐
                    │ Infrastructure Node  │
                    │ (NFS Server)         │
                    │                      │
                    │ /data/dynamic-storage│
                    └──────────────────────┘
```

## Use Cases

### Development/Testing
- Single provisioner as default
- Quick storage for development workloads

### Production Multi-Tier
- **Tier 1**: Fast SSD-backed NFS for databases
- **Tier 2**: Standard storage for application data
- **Tier 3**: Bulk storage for logs/backups

### Team Isolation
- Separate provisioner per team/project
- Independent quotas and policies

## Notes

- The provisioner uses `ReadWriteMany` (RWX) access mode
- Reclaim policy is `Delete` by default (PV deleted when PVC is deleted)
- Volume expansion is enabled
- NFS server must be reachable from all cluster nodes

## References

- [NFS Subdir External Provisioner](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner)
- [OpenShift Storage Documentation](https://docs.openshift.com/container-platform/latest/storage/index.html)
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

## Support

For issues or questions:
1. Check the Troubleshooting section
2. Review provisioner logs: `oc logs -n nfs-provisioner -l app=nfs-subdir-external-provisioner`
3. Verify NFS server configuration
4. Check OpenShift events: `oc get events -n nfs-provisioner --sort-by='.lastTimestamp'`