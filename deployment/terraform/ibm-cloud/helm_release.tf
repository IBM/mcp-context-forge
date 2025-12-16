##################################
# Deploy the application via Helm
##################################
resource "helm_release" "mcpgw" {
  name       = "mcpgateway"
  repository = "oci://ghcr.io/ibm/mcp-context-forge-chart/mcp-context-forge-chart"
  chart      = "mcpgateway"
  version    = "1.0.0-BETA-1"

  values = [
    yamlencode({
      image = {
        repository = var.gateway_image
        tag        = "latest"
        pullPolicy = "IfNotPresent"
      }
      replicaCount = var.gateway_replicas
      envFrom = [
        { secretRef   = { name = kubernetes_secret.mcpgw.metadata[0].name } },
        { configMapRef = { name = kubernetes_config_map.mcpgw_env.metadata[0].name } }
      ]
      service = { type = "ClusterIP", port = 80 }
      ingress = {
        enabled   = true
        className = "public-iks-k8s-nginx"
        hosts     = [
          {
            host  = "gateway.${var.prefix}.apps.${var.region}.containers.appdomain.cloud"
            paths = ["/"]
          }
        ]
        tls = [
          {
            hosts = ["gateway.${var.prefix}.apps.${var.region}.containers.appdomain.cloud"]
          }
        ]
      }
    })
  ]
}
