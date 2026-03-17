package controller

import (
	"context"
	"fmt"
	"strconv"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
	"sigs.k8s.io/controller-runtime/pkg/client"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

const (
	defaultGatewayImage = "contextforge:latest"
	gatewayPort         = 4444
)

// reconcileGateway creates or updates the gateway ConfigMap, Deployment, and Service.
func reconcileGateway(ctx context.Context, c client.Client, cf *cfv1.ContextForge, dbURL, dbSecretName, redisURL string) error {
	if err := reconcileGatewayConfigMap(ctx, c, cf, dbURL, redisURL); err != nil {
		return fmt.Errorf("gateway configmap: %w", err)
	}
	if err := reconcileGatewayDeployment(ctx, c, cf, dbSecretName); err != nil {
		return fmt.Errorf("gateway deployment: %w", err)
	}
	if err := reconcileGatewayService(ctx, c, cf); err != nil {
		return fmt.Errorf("gateway service: %w", err)
	}
	return nil
}

func reconcileGatewayConfigMap(ctx context.Context, c client.Client, cf *cfv1.ContextForge, dbURL, redisURL string) error {
	name := nameFor(cf, "gateway-config")
	cm := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, cm, func() error {
		cm.Labels = commonLabels(cf, "gateway")
		gw := cf.Spec.Gateway

		httpServer := gw.HTTPServer
		if httpServer == "" {
			httpServer = "gunicorn"
		}
		workers := int32(4)
		if gw.Workers != nil {
			workers = *gw.Workers
		}

		data := map[string]string{
			"HOST":       "0.0.0.0",
			"PORT":       strconv.Itoa(gatewayPort),
			"REDIS_URL":  redisURL,
			"CACHE_TYPE": "redis",

			"HTTP_SERVER": httpServer,

			// Auth
			"AUTH_REQUIRED":       "true",
			"MCP_REQUIRE_AUTH":    "true",
			"JWT_ALGORITHM":       "HS256",
			"JWT_AUDIENCE":        "mcpgateway-api",
			"JWT_ISSUER":          "mcpgateway",
			"PLATFORM_ADMIN_EMAIL": cf.Spec.Auth.AdminEmail,

			// Performance: match docker-compose production tuning
			"DB_POOL_SIZE":       "20",
			"DB_MAX_OVERFLOW":    "10",
			"DB_POOL_TIMEOUT":    "60",
			"DB_POOL_RECYCLE":    "60",
			"DB_POOL_PRE_PING":   "true",
			"DB_MAX_RETRIES":     "30",
			"REDIS_MAX_CONNECTIONS": "100",

			// HTTPX client pool
			"HTTPX_MAX_CONNECTIONS":           "500",
			"HTTPX_MAX_KEEPALIVE_CONNECTIONS": "300",
			"HTTPX_KEEPALIVE_EXPIRY":          "30.0",
			"HTTPX_READ_TIMEOUT":              "120.0",

			// Caching (enabled by default per docker-compose)
			"AUTH_CACHE_ENABLED":     "true",
			"REGISTRY_CACHE_ENABLED": "true",
			"METRICS_CACHE_ENABLED":  "true",

			// Logging
			"LOG_LEVEL":           "INFO",
			"DISABLE_ACCESS_LOG":  "true",

			// MCP transport
			"TRANSPORT_TYPE":            "all",
			"MCP_SESSION_POOL_ENABLED":  "true",
		}

		// Database URL: if managed, it will be injected via env var to
		// avoid embedding the password in a ConfigMap. The URL template
		// has the password omitted, and the Deployment adds it via env.
		if dbURL != "" {
			data["DATABASE_URL"] = dbURL
		}

		// HTTP server workers
		if httpServer == "gunicorn" {
			data["GUNICORN_WORKERS"] = strconv.Itoa(int(workers))
			data["GUNICORN_TIMEOUT"] = "120"
			data["GUNICORN_BACKLOG"] = "4096"
			data["GUNICORN_KEEP_ALIVE"] = "30"
		} else {
			data["GRANIAN_WORKERS"] = strconv.Itoa(int(workers))
			data["GRANIAN_BACKLOG"] = "4096"
			data["GRANIAN_BACKPRESSURE"] = "128"
		}

		// Features
		if cf.Spec.Features != nil {
			f := cf.Spec.Features
			data["MCPGATEWAY_UI_ENABLED"] = strconv.FormatBool(boolVal(f.UI, true))
			data["MCPGATEWAY_ADMIN_API_ENABLED"] = strconv.FormatBool(boolVal(f.AdminAPI, true))
			data["MCPGATEWAY_A2A_ENABLED"] = strconv.FormatBool(boolVal(f.A2A, true))
			data["PLUGINS_ENABLED"] = strconv.FormatBool(boolVal(f.Plugins, false))
			data["MCPGATEWAY_CATALOG_ENABLED"] = strconv.FormatBool(boolVal(f.Catalog, true))
			if f.RustRuntime != nil && f.RustRuntime.Mode != "" && f.RustRuntime.Mode != "off" {
				data["RUST_MCP_MODE"] = f.RustRuntime.Mode
				data["EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED"] = "true"
			}
		} else {
			data["MCPGATEWAY_UI_ENABLED"] = "true"
			data["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
			data["MCPGATEWAY_A2A_ENABLED"] = "true"
			data["PLUGINS_ENABLED"] = "false"
			data["MCPGATEWAY_CATALOG_ENABLED"] = "true"
		}

		cm.Data = data
		return nil
	})
}

func reconcileGatewayDeployment(ctx context.Context, c client.Client, cf *cfv1.ContextForge, dbSecretName string) error {
	gw := cf.Spec.Gateway
	name := nameFor(cf, "gateway")
	labels := commonLabels(cf, "gateway")
	selector := selectorLabels(cf, "gateway")

	image := gw.Image
	if image == "" {
		image = defaultGatewayImage
	}
	replicas := int32(1)
	if gw.Replicas != nil {
		replicas = *gw.Replicas
	}

	configMapName := nameFor(cf, "gateway-config")
	jwtSecretName := nameFor(cf, "jwt-secret")
	if cf.Spec.Auth.JWTSecretRef != nil {
		jwtSecretName = cf.Spec.Auth.JWTSecretRef.Name
	}

	dep := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, dep, func() error {
		dep.Labels = labels
		dep.Spec = appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: selector},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: boolPtr(true),
					},
					Containers: []corev1.Container{{
						Name:  "gateway",
						Image: image,
						Ports: []corev1.ContainerPort{{
							Name: "http", ContainerPort: gatewayPort, Protocol: corev1.ProtocolTCP,
						}},
						EnvFrom: []corev1.EnvFromSource{{
							ConfigMapRef: &corev1.ConfigMapEnvSource{
								LocalObjectReference: corev1.LocalObjectReference{Name: configMapName},
							},
						}},
						Env: gatewaySecretEnv(cf, jwtSecretName, dbSecretName),
						ReadinessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{
									Path: "/ready", Port: intstr.FromInt32(gatewayPort),
								},
							},
							InitialDelaySeconds: 10,
							PeriodSeconds:       15,
							TimeoutSeconds:      10,
						},
						LivenessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{
									Path: "/health", Port: intstr.FromInt32(gatewayPort),
								},
							},
							InitialDelaySeconds: 30,
							PeriodSeconds:       30,
							TimeoutSeconds:      10,
						},
						StartupProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{
									Path: "/health", Port: intstr.FromInt32(gatewayPort),
								},
							},
							InitialDelaySeconds: 5,
							PeriodSeconds:       5,
							TimeoutSeconds:      10,
							FailureThreshold:    30,
						},
						SecurityContext: &corev1.SecurityContext{
							AllowPrivilegeEscalation: boolPtr(false),
							RunAsUser:                int64Ptr(1001),
						},
						Resources: resourcesOrDefault(gw.Resources, corev1.ResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceCPU:    resource.MustParse("500m"),
								corev1.ResourceMemory: resource.MustParse("768Mi"),
							},
							Limits: corev1.ResourceList{
								corev1.ResourceMemory: resource.MustParse("2Gi"),
							},
						}),
					}},
				},
			},
		}
		// Append user-defined env vars
		if len(gw.Env) > 0 {
			dep.Spec.Template.Spec.Containers[0].Env = append(
				dep.Spec.Template.Spec.Containers[0].Env,
				gw.Env...,
			)
		}
		return nil
	})
}

// gatewaySecretEnv returns env vars sourced from secrets (JWT key, DB password).
func gatewaySecretEnv(cf *cfv1.ContextForge, jwtSecretName, dbSecretName string) []corev1.EnvVar {
	envs := []corev1.EnvVar{
		{
			Name: "JWT_SECRET_KEY",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: jwtSecretName},
					Key:                  "secret",
				},
			},
		},
	}
	// If using managed DB, inject password from the postgres-credentials secret
	if dbSecretName != "" {
		envs = append(envs, corev1.EnvVar{
			Name: "DATABASE_PASSWORD",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{Name: dbSecretName},
					Key:                  "password",
				},
			},
		})
	}
	return envs
}

func reconcileGatewayService(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	name := nameFor(cf, "gateway")
	labels := commonLabels(cf, "gateway")
	selector := selectorLabels(cf, "gateway")

	svc := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, svc, func() error {
		svc.Labels = labels
		svc.Spec = corev1.ServiceSpec{
			Selector: selector,
			Ports: []corev1.ServicePort{{
				Name: "http", Port: 80, TargetPort: intstr.FromInt32(gatewayPort), Protocol: corev1.ProtocolTCP,
			}},
		}
		return nil
	})
}
