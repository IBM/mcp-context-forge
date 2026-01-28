terraform {
  required_version = ">= 1.6"

  required_providers {
    ibm        = { source = "IBM-Cloud/ibm",  version = ">= 2.12.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.24.0" }
    helm       = { source = "hashicorp/helm",       version = ">= 2.13.2" }
  }
}
