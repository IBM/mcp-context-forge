# MCP Context-Forge - Ansible Deployment

This folder spins up:

1. A resource-group + VPC IKS cluster
2. Databases-for-PostgreSQL & Databases-for-Redis
3. Service-keys → Kubernetes Secrets
4. The container `ghcr.io/ibm/mcp-context-forge:v0.2.0` behind an Ingress URL

## Prerequisites

* **IBM Cloud CLI** authenticated (`ibmcloud login ...`)
* Ansible ≥ 2.12 with the Galaxy collections in `requirements.yml`
* `helm`, `kubectl`, and `ibmcloud ks` binaries in `$PATH`

## One-liner

```bash
cd ansible
ansible-playbook site.yml \
  -e region=eu-gb \
  -e prefix=demo
```

The play will finish with the public URL:

```
https://gateway.<prefix>.apps.<region>.containers.appdomain.cloud
```

---

### Using the playbook

```bash
# Bootstrap collections & run
ansible-galaxy install -r ansible/requirements.yml
ansible-playbook ansible/site.yml
```
