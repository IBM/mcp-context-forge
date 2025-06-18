##################################
# Managed Databases for Redis
##################################
resource "ibm_resource_instance" "redis" {
  name       = "${var.prefix}-redis"
  service    = "databases-for-redis"
  plan       = "standard"
  location   = var.region
  parameters = { version = var.redis_version }
}

resource "ibm_resource_key" "redis_key" {
  name                 = "${var.prefix}-redis-key"
  role                 = "Administrator"
  resource_instance_id = ibm_resource_instance.redis.id
}
