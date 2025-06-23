# IBM Cloud provider (regional)
provider "ibm" {
  region         = var.region
  resource_group = ibm_resource_group.app.id
}

# NOTE: The kubernetes & helm providers are *re-configured later*
#       once the IKS cluster is up and the config is fetched.
provider "kubernetes" {}
provider "helm"       {}
