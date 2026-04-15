# Ansible Playbooks for OCP Deployment (Experimental)

Deploy and benchmark ContextForge on OpenShift using Ansible playbooks. These playbooks are an alternative to the `make ocp-*` targets — both coexist and do the same thing under the hood.

## Prerequisites

- `ansible` installed (`pip install ansible`)
- `kubernetes.core` collection (`ansible-galaxy collection install kubernetes.core`)
- `oc` CLI authenticated to your cluster
- `helm` CLI available
- CrunchyData PGO operator installed on the cluster
- Secrets file created at `charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml`

## Quick Start

```bash
# 1. Set up namespace + PostgresCluster + schema privileges
ansible-playbook ansible/ocp/playbooks/setup.yml -i ansible/ocp/inventory/cluster.yml

# 2. Deploy the full stack
ansible-playbook ansible/ocp/playbooks/deploy.yml -i ansible/ocp/inventory/cluster.yml

# 3. Enable Locust and configure benchmark
ansible-playbook ansible/ocp/playbooks/benchmark-setup.yml -i ansible/ocp/inventory/cluster.yml

# 4. Run the benchmark
ansible-playbook ansible/ocp/playbooks/benchmark.yml -i ansible/ocp/inventory/cluster.yml

# 5. Uninstall (preserves Postgres + namespace)
ansible-playbook ansible/ocp/playbooks/uninstall.yml -i ansible/ocp/inventory/cluster.yml
```

## Override Variables

Override any default at runtime with `-e`:

```bash
# Different namespace
ansible-playbook ansible/ocp/playbooks/deploy.yml -i ansible/ocp/inventory/cluster.yml -e ocp_namespace=my-namespace

# Heavy load benchmark
ansible-playbook ansible/ocp/playbooks/benchmark.yml -i ansible/ocp/inventory/cluster.yml -e bench_users=500 -e bench_spawn=50

# Skip confirmation prompts
ansible-playbook ansible/ocp/playbooks/deploy.yml -i ansible/ocp/inventory/cluster.yml -e skip_confirm=true
```

## Available Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ocp_namespace` | `contextforge` | Namespace and Helm release name |
| `ocp_values` | `charts/mcp-stack/profiles/ocp/values-pgo.yaml` | Helm values file |
| `ocp_secrets` | `charts/mcp-stack/profiles/ocp/values-pgo-secrets.yaml` | Secrets override file |
| `ocp_pg_cr` | `charts/mcp-stack/profiles/ocp/manifests/pgo-postgrescluster.yaml` | PostgresCluster CR |
| `bench_users` | `125` | Number of simulated users |
| `bench_spawn` | `30` | Users spawned per second |
| `bench_runtime` | `60s` | Benchmark duration |
| `skip_confirm` | `false` | Skip confirmation prompts |

Defaults are in `vars/defaults.yml`. Override via inventory, vars files, or `-e`.

## Playbooks

| Playbook | Equivalent Make target | Description |
|----------|----------------------|-------------|
| `setup.yml` | `make ocp-setup` | PGO operator check, namespace, PostgresCluster CR, schema privileges |
| `deploy.yml` | `make ocp-deploy` | Helm install (gateway, NGINX, Redis, fast-time-server) |
| `benchmark-setup.yml` | `make ocp-benchmark-setup` | Enable Locust, fetch server ID, wait for workers |
| `benchmark.yml` | `make ocp-benchmark` | Trigger the MCP benchmark |
| `uninstall.yml` | `make ocp-uninstall` | Helm uninstall (preserves Postgres + namespace) |

## Inventory

Edit `inventory/cluster.yml` to configure your cluster. The default runs against `localhost` using the current `oc` session. Override variables per-cluster in the inventory file.

## Comparison with Make Targets

| Aspect | Make | Ansible |
|--------|------|---------|
| Dependencies | `make`, `oc`, `helm` | `ansible`, `oc`, `helm`, `kubernetes.core` |
| Configuration | CLI variables (`OCP_NS=...`) | Inventory files + `-e` overrides |
| Multi-cluster | One cluster at a time | Inventory-based, switch clusters by file |
| Confirmation prompts | `read -p` (bash) | `pause` module (skippable via `skip_confirm`) |
| Error handling | bash `set -e` / `||` | Ansible `block/rescue`, `failed_when`, `assert` |
