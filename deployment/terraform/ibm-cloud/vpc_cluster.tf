######################
# IBM Cloud – VPC IKS
######################
resource "ibm_container_vpc_cluster" "iks" {
  name            = "${var.prefix}-iks"
  kube_version    = "1.29"
  flavor          = "bx2.4x16"     # 4 vCPU / 16 GiB
  worker_count    = var.k8s_workers
  entitlement     = "cloud_pak"
  wait_till_ready = true
}

##############################
# Pull cluster-config details
##############################
data "ibm_container_cluster_config" "conf" {
  cluster_name_id = ibm_container_vpc_cluster.iks.id
}

##############################
# Re-configure K8s providers
##############################
provider "kubernetes" {
  host                   = data.ibm_container_cluster_config.conf.server_url
  token                  = data.ibm_container_cluster_config.conf.token
  cluster_ca_certificate = base64decode(data.ibm_container_cluster_config.conf.ca_certificate)
}

provider "helm" {
  kubernetes {
    host                   = data.ibm_container_cluster_config.conf.server_url
    token                  = data.ibm_container_cluster_config.conf.token
    cluster_ca_certificate = base64decode(data.ibm_container_cluster_config.conf.ca_certificate)
  }
}
