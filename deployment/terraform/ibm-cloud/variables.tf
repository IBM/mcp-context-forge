variable "region" {
  description = "IBM Cloud region for all resources (e.g. eu-gb, us-south)"
  type        = string
}

variable "prefix" {
  description = "Name prefix for all IBM Cloud assets"
  type        = string
  default     = "mcpgw"
}

variable "k8s_workers" {
  description = "Number of worker nodes per zone"
  type        = number
  default     = 1
}

variable "postgres_version" {
  description = "PostgreSQL major version"
  type        = string
  default     = "14"
}

variable "redis_version" {
  description = "Redis major version"
  type        = string
  default     = "7"
}

variable "gateway_image" {
  description = "OCI image reference for the MCP Gateway container"
  type        = string
  default     = "icr.io/your-namespace/mcpgateway:latest"
}

variable "gateway_replicas" {
  description = "Number of MCP Gateway pods"
  type        = number
  default     = 2
}
