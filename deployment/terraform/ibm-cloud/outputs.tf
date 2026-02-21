output "gateway_url" {
  description = "FQDN for ContextForge ingress"
  value       = "https://gateway.${var.prefix}.apps.${var.region}.containers.appdomain.cloud"
}

output "postgres_connection" {
  description = "PostgreSQL connection string (sensitive)"
  value       = ibm_resource_key.pg_key.connection[0].postgres["composed"][0]
  sensitive   = true
}

output "redis_connection" {
  description = "Redis TLS connection string (sensitive)"
  value       = ibm_resource_key.redis_key.connection[0].rediss["composed"][0]
  sensitive   = true
}
