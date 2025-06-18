resource "ibm_resource_group" "app" {
  name = "${var.prefix}-rg"
}
