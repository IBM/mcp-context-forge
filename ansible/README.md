# Ansible Deployment Playbooks

[Experimental] Ansible playbooks for deploying and benchmarking ContextForge across different platforms.

## Available Platforms

| Platform | Path | Description |
|----------|------|-------------|
| [OpenShift (OCP)](ocp/) | `ansible/ocp/` | [Experimental] Deploy with CrunchyData PGO, dynamic NFS provisioning, MCP benchmark |

## Getting Started

1. Install Ansible: `pip install ansible`
2. Install the Kubernetes collection: `ansible-galaxy collection install kubernetes.core`
3. Navigate to the platform directory (e.g. `ansible/ocp/`) and follow the README
