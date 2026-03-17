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
	defaultPostgresImage = "postgres:18"
	postgresPort         = 5432
	postgresDBName       = "mcp"
	postgresUser         = "postgres"
)

// reconcileDatabaseFull ensures the database is configured and returns
// (url-template, secret-name, error). For managed databases, the URL omits
// the password which is injected separately via an env-var reference.
func reconcileDatabaseFull(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (dbURL string, dbSecretName string, err error) {
	if cf.Spec.Database.External != nil {
		url, err := externalDatabaseURL(ctx, c, cf)
		return url, "", err
	}
	if cf.Spec.Database.Managed == nil {
		return "", "", fmt.Errorf("spec.database: one of managed or external must be set")
	}
	if err := reconcileManagedPostgres(ctx, c, cf); err != nil {
		return "", "", err
	}
	svcName := nameFor(cf, "postgres")
	secretName := nameFor(cf, "postgres-credentials")
	url := fmt.Sprintf("postgresql+psycopg://%s@%s:%d/%s",
		postgresUser, svcName, postgresPort, postgresDBName)
	return url, secretName, nil
}

func externalDatabaseURL(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (string, error) {
	ext := cf.Spec.Database.External
	if ext.URL != "" {
		return ext.URL, nil
	}
	if ext.SecretRef != nil {
		secret := &corev1.Secret{}
		if err := c.Get(ctx, client.ObjectKey{Name: ext.SecretRef.Name, Namespace: cf.Namespace}, secret); err != nil {
			return "", fmt.Errorf("cannot read database secret %q: %w", ext.SecretRef.Name, err)
		}
		if url, ok := secret.Data["url"]; ok {
			return string(url), nil
		}
		return "", fmt.Errorf("database secret %q missing key \"url\"", ext.SecretRef.Name)
	}
	return "", fmt.Errorf("spec.database.external: one of url or secretRef must be set")
}

func reconcileManagedPostgres(ctx context.Context, c client.Client, cf *cfv1.ContextForge) error {
	managed := cf.Spec.Database.Managed
	image := managed.Image
	if image == "" {
		image = defaultPostgresImage
	}

	secretName := nameFor(cf, "postgres-credentials")
	if err := ensureSecret(ctx, c, cf, secretName, map[string][]byte{
		"password": []byte("contextforge-db-" + cf.Name),
		"username": []byte(postgresUser),
		"database": []byte(postgresDBName),
	}); err != nil {
		return fmt.Errorf("postgres credentials: %w", err)
	}

	name := nameFor(cf, "postgres")
	labels := commonLabels(cf, "postgres")
	selector := selectorLabels(cf, "postgres")

	storageSize := managed.StorageSize
	if storageSize.IsZero() {
		storageSize = resource.MustParse("5Gi")
	}

	// StatefulSet
	ss := &appsv1.StatefulSet{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: cf.Namespace}}
	if err := createOrUpdate(ctx, c, cf, ss, func() error {
		ss.Labels = labels
		ss.Spec = appsv1.StatefulSetSpec{
			ServiceName: name,
			Replicas:    int32Ptr(1),
			Selector:    &metav1.LabelSelector{MatchLabels: selector},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: boolPtr(true),
						FSGroup:      int64Ptr(999),
					},
					Containers: []corev1.Container{{
						Name:  "postgres",
						Image: image,
						Ports: []corev1.ContainerPort{{
							Name: "postgres", ContainerPort: postgresPort, Protocol: corev1.ProtocolTCP,
						}},
						Env: []corev1.EnvVar{
							{Name: "POSTGRES_DB", Value: postgresDBName},
							{Name: "POSTGRES_USER", Value: postgresUser},
							{Name: "POSTGRES_PASSWORD", ValueFrom: &corev1.EnvVarSource{
								SecretKeyRef: &corev1.SecretKeySelector{
									LocalObjectReference: corev1.LocalObjectReference{Name: secretName},
									Key:                  "password",
								},
							}},
							// Performance tuning from docker-compose
							{Name: "POSTGRES_INITDB_ARGS", Value: "--auth-host=scram-sha-256"},
						},
						Args: []string{
							"-c", "max_connections=800",
							"-c", "shared_buffers=256MB",
							"-c", "work_mem=16MB",
							"-c", "synchronous_commit=off",
							"-c", "idle_in_transaction_session_timeout=300000",
							"-c", "statement_timeout=120000",
						},
						ReadinessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								Exec: &corev1.ExecAction{
									Command: []string{"pg_isready", "-U", postgresUser, "-d", postgresDBName},
								},
							},
							InitialDelaySeconds: 5,
							PeriodSeconds:       10,
							TimeoutSeconds:      5,
						},
						LivenessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								Exec: &corev1.ExecAction{
									Command: []string{"pg_isready", "-U", postgresUser, "-d", postgresDBName},
								},
							},
							InitialDelaySeconds: 30,
							PeriodSeconds:       30,
							TimeoutSeconds:      5,
						},
						VolumeMounts: []corev1.VolumeMount{{
							Name: "data", MountPath: "/var/lib/postgresql/data",
						}},
						SecurityContext: &corev1.SecurityContext{
							AllowPrivilegeEscalation: boolPtr(false),
						},
						Resources: resourcesOrDefault(managed.Resources, corev1.ResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceCPU:    resource.MustParse("250m"),
								corev1.ResourceMemory: resource.MustParse("512Mi"),
							},
							Limits: corev1.ResourceList{
								corev1.ResourceMemory: resource.MustParse("1Gi"),
							},
						}),
					}},
				},
			},
			VolumeClaimTemplates: []corev1.PersistentVolumeClaim{{
				ObjectMeta: metav1.ObjectMeta{Name: "data"},
				Spec: corev1.PersistentVolumeClaimSpec{
					AccessModes:      []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
					StorageClassName: managed.StorageClassName,
					Resources: corev1.VolumeResourceRequirements{
						Requests: corev1.ResourceList{
							corev1.ResourceStorage: storageSize,
						},
					},
				},
			}},
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
				Name: "postgres", Port: postgresPort, TargetPort: intstr.FromInt32(postgresPort), Protocol: corev1.ProtocolTCP,
			}},
			ClusterIP: corev1.ClusterIPNone,
		}
		return nil
	})
}

func boolPtr(b bool) *bool   { return &b }
func int64Ptr(i int64) *int64 { return &i }

func resourcesOrDefault(r *corev1.ResourceRequirements, def corev1.ResourceRequirements) corev1.ResourceRequirements {
	if r != nil {
		return *r
	}
	return def
}
