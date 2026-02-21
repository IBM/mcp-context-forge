# ContextForge - Terraform IaaS + PaaS Layer

Deploys an IKS cluster plus managed PostgreSQL & Redis on IBM Cloud,
then rolls out the ContextForge container via Helm.

## Prerequisites

* Terraform ≥ 1.6
* IBM Cloud CLI logged in with at least **Editor** on the target account
  (`ibmcloud login && ibmcloud iam oauth-tokens`)
* `KUBECONFIG` *not* set (the provider fetches cluster config for you)

## Quick Start

```bash
# 1 - configure your region / prefix
export TF_VAR_region="eu-gb"
export TF_VAR_prefix="demo"

# 2 - kick the tyres
terraform init
terraform plan -out tfplan
terraform apply tfplan   # ~15 mins

# 3 - hit the app 🎉
terraform output -raw gateway_url
```

## Day-2 Operations

| Task                  | Where / How                                       |
| --------------------- | ------------------------------------------------- |
| Scale pods            | `helm upgrade mcpgateway ... --set replicaCount=N`  |
| Rotate DB credentials | `terraform taint ibm_resource_key.pg_key` → apply |
| View cluster          | `ibmcloud ks cluster config --cluster <id>`       |
| Destroy everything    | `terraform destroy`                               |

All resources live in their own resource-group; state is fully reproducible.
