#####################################
# Managed Databases for PostgreSQL
#####################################
resource "ibm_resource_instance" "postgres" {
  name       = "${var.prefix}-pg"
  service    = "databases-for-postgresql"
  plan       = "standard"
  location   = var.region
  parameters = { version = var.postgres_version }
}

resource "ibm_resource_key" "pg_key" {
  name                 = "${var.prefix}-pg-key"
  role                 = "Administrator"
  resource_instance_id = ibm_resource_instance.postgres.id
}
