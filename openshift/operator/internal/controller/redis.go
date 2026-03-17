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
	defaultRedisImage = "redis:latest"
	redisPort         = 6379
)

// reconcileRedis ensures managed or external Redis is configured.
// Returns the REDIS_URL to inject into the gateway.
func reconcileRedis(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (string, error) {
	if cf.Spec.Redis.External != nil {
		return externalRedisURL(ctx, c, cf)
	}
	if cf.Spec.Redis.Managed == nil {
		return "", fmt.Errorf("spec.redis: one of managed or external must be set")
	}
	if err := reconcileManagedRedis(ctx, c, cf); err != nil {
		return "", err
	}
	svcName := nameFor(cf, "redis")
	return fmt.Sprintf("redis://%s:%d/0", svcName, redisPort), nil
}

func externalRedisURL(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (string, error) {
	ext := cf.Spec.Redis.External
	if ext.URL != "" {
		return ext.URL, nil
	}
	if ext.SecretRef != nil {
		secret := &corev1.Secret{}
		if err := c.Get(ctx, client.ObjectKey{Name: ext.SecretRef.Name, Namespace: cf.Namespace}, secret); err != nil {
			return "", fmt.Errorf("cannot read redis secret %q: %w", ext.SecretRef.Name, err)
		}
		if url, ok := secret.Data["url"]; ok {
			return string(url), nil
		}
		return "", fmt.Errorf("redis secret %q missing key \"url\"", ext.SecretRef.Name)
	}
	return "", fmt.Errorf("spec.redis.external: one of url or secretRef must be set")
}

func reconcileManagedRedis(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	managed := cf.Spec.Redis.Managed
	image := managed.Image
	if image == "" {
		image = defaultRedisImage
	}

	name := nameFor(cf, "redis")
	labels := commonLabels(cf, "redis")
	selector := selectorLabels(cf, "redis")

	// Deployment
	dep := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	if err := createOrUpdate(ctx, c, cf, dep, func() error {
		dep.Labels = labels
		dep.Spec = appsv1.DeploymentSpec{
			Replicas: int32Ptr(1),
			Selector: &metav1.LabelSelector{MatchLabels: selector},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: boolPtr(true),
						RunAsUser:    int64Ptr(999),
					},
					Containers: []corev1.Container{{
						Name:  "redis",
						Image: image,
						// Match docker-compose: tuned for 1000+ RPS
						Args: []string{
							"redis-server",
							"--maxmemory", "1gb",
							"--maxmemory-policy", "allkeys-lru",
							"--maxclients", "10000",
							"--timeout", "300",
							"--tcp-keepalive", "60",
							"--hz", "50",
							"--save", "",
							"--appendonly", "no",
						},
						Ports: []corev1.ContainerPort{{
							Name: "redis", ContainerPort: redisPort, Protocol: corev1.ProtocolTCP,
						}},
						ReadinessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								Exec: &corev1.ExecAction{
									Command: []string{"redis-cli", "PING"},
								},
							},
							InitialDelaySeconds: 5,
							PeriodSeconds:       15,
							TimeoutSeconds:      5,
						},
						LivenessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								Exec: &corev1.ExecAction{
									Command: []string{"redis-cli", "PING"},
								},
							},
							InitialDelaySeconds: 15,
							PeriodSeconds:       15,
							TimeoutSeconds:      5,
						},
						SecurityContext: &corev1.SecurityContext{
							AllowPrivilegeEscalation: boolPtr(false),
						},
						Resources: resourcesOrDefault(managed.Resources, corev1.ResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceCPU:    resource.MustParse("100m"),
								corev1.ResourceMemory: resource.MustParse("256Mi"),
							},
							Limits: corev1.ResourceList{
								corev1.ResourceMemory: resource.MustParse("1Gi"),
							},
						}),
					}},
				},
			},
		}
		return nil
	}); err != nil {
		return err
	}

	// Service
	svc := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	return createOrUpdate(ctx, c, cf, svc, func() error {
		svc.Labels = labels
		svc.Spec = corev1.ServiceSpec{
			Selector: selector,
			Ports: []corev1.ServicePort{{
				Name: "redis", Port: redisPort, TargetPort: intstr.FromInt32(redisPort), Protocol: corev1.ProtocolTCP,
			}},
		}
		return nil
	})
}
