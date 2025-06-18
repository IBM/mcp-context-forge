#########################
# App secrets & config
#########################

locals {
  pg_conn    = ibm_resource_key.pg_key.connection[0]
  redis_conn = ibm_resource_key.redis_key.connection[0]
}

# JWT signing secret
resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "kubernetes_secret" "mcpgw" {
  metadata { name = "mcpgateway-secrets" }
  type     = "Opaque"
  data = {
    DATABASE_URL = base64encode(local.pg_conn.postgres["composed"][0])
    REDIS_URL    = base64encode(local.redis_conn.rediss["composed"][0])
    JWT_SECRET   = base64encode(random_password.jwt.result)
  }
}

resource "kubernetes_config_map" "mcpgw_env" {
  metadata { name = "mcpgateway-env" }
  data = {
    APP_NAME  = "MCP Gateway"
    LOG_LEVEL = "INFO"
  }
}
