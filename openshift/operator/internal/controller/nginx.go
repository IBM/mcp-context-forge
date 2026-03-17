package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
	"sigs.k8s.io/controller-runtime/pkg/client"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

const (
	defaultNginxImage = "nginx-cache:latest"
	nginxHTTPPort     = 8080
)

func reconcileNginx(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	nginx := cf.Spec.Nginx
	if nginx == nil || !nginx.Enabled {
		return nil
	}
	if err := reconcileNginxConfigMap(ctx, c, cf); err != nil {
		return fmt.Errorf("nginx configmap: %w", err)
	}
	if err := reconcileNginxDeployment(ctx, c, cf); err != nil {
		return fmt.Errorf("nginx deployment: %w", err)
	}
	return reconcileNginxService(ctx, c, cf)
}

func reconcileNginxConfigMap(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	name := nameFor(cf, "nginx-config")
	gatewaySvc := nameFor(cf, "gateway")

	cm := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, cm, func() error {
		cm.Labels = commonLabels(cf, "nginx")
		// Minimal nginx.conf that proxies to the gateway service.
		// Based on the production infra/nginx/nginx.conf from docker-compose.
		cm.Data = map[string]string{
			"nginx.conf": fmt.Sprintf(`worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 1000;

    # Upstream: gateway service
    upstream gateway {
        server %s:80;
        keepalive 64;
    }

    # Cache zones
    proxy_cache_path /var/cache/nginx/api levels=1:2 keys_zone=api_cache:10m max_size=256m inactive=5m;
    proxy_cache_path /var/cache/nginx/static levels=1:2 keys_zone=static_cache:10m max_size=512m inactive=1h;

    server {
        listen 80;
        server_name _;

        # Health endpoint
        location /health {
            proxy_pass http://gateway;
            proxy_set_header Host $host;
        }

        # Static assets with aggressive caching
        location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
            proxy_pass http://gateway;
            proxy_cache static_cache;
            proxy_cache_valid 200 1h;
            add_header X-Cache-Status $upstream_cache_status;
        }

        # SSE/WebSocket: no buffering
        location ~ ^/(sse|ws|mcp) {
            proxy_pass http://gateway;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
        }

        # API with short-lived cache
        location /api/ {
            proxy_pass http://gateway;
            proxy_cache api_cache;
            proxy_cache_valid 200 30s;
            proxy_cache_use_stale error timeout updating;
            add_header X-Cache-Status $upstream_cache_status;
        }

        # Everything else
        location / {
            proxy_pass http://gateway;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
        }
    }
}
`, gatewaySvc),
		}
		return nil
	})
}

func reconcileNginxDeployment(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	nginx := cf.Spec.Nginx
	image := nginx.Image
	if image == "" {
		image = defaultNginxImage
	}

	name := nameFor(cf, "nginx")
	labels := commonLabels(cf, "nginx")
	selector := selectorLabels(cf, "nginx")
	configMapName := nameFor(cf, "nginx-config")

	dep := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, dep, func() error {
		dep.Labels = labels
		dep.Spec = appsv1.DeploymentSpec{
			Replicas: int32Ptr(1),
			Selector: &metav1.LabelSelector{MatchLabels: selector},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{
						Name:  "nginx",
						Image: image,
						Ports: []corev1.ContainerPort{{
							Name: "http", ContainerPort: 80, Protocol: corev1.ProtocolTCP,
						}},
						VolumeMounts: []corev1.VolumeMount{{
							Name:      "nginx-config",
							MountPath: "/etc/nginx/nginx.conf",
							SubPath:   "nginx.conf",
							ReadOnly:  true,
						}},
						ReadinessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{
									Path: "/health", Port: intstr.FromInt32(80),
								},
							},
							InitialDelaySeconds: 5,
							PeriodSeconds:       15,
						},
						LivenessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{
									Path: "/health", Port: intstr.FromInt32(80),
								},
							},
							InitialDelaySeconds: 10,
							PeriodSeconds:       30,
						},
						Resources: resourcesOrDefault(nginx.Resources, corev1.ResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceCPU:    resource.MustParse("100m"),
								corev1.ResourceMemory: resource.MustParse("128Mi"),
							},
							Limits: corev1.ResourceList{
								corev1.ResourceMemory: resource.MustParse("512Mi"),
							},
						}),
					}},
					Volumes: []corev1.Volume{{
						Name: "nginx-config",
						VolumeSource: corev1.VolumeSource{
							ConfigMap: &corev1.ConfigMapVolumeSource{
								LocalObjectReference: corev1.LocalObjectReference{Name: configMapName},
							},
						},
					}},
				},
			},
		}
		return nil
	})
}

func reconcileNginxService(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	name := nameFor(cf, "nginx")
	labels := commonLabels(cf, "nginx")
	selector := selectorLabels(cf, "nginx")

	svc := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, svc, func() error {
		svc.Labels = labels
		svc.Spec = corev1.ServiceSpec{
			Selector: selector,
			Ports: []corev1.ServicePort{{
				Name: "http", Port: int32(nginxHTTPPort), TargetPort: intstr.FromInt32(80), Protocol: corev1.ProtocolTCP,
			}},
		}
		return nil
	})
}
