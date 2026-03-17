package controller

import (
	"context"
	"fmt"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

// reconcileMigration creates or checks the Alembic database migration Job.
// Returns true if the migration is complete.
func reconcileMigration(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (bool, error) {
	name := nameFor(cf, "migration")
	labels := commonLabels(cf, "migration")

	// Check if migration Job already exists and is complete
	existing := &batchv1.Job{}
	err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: cf.Namespace}, existing)
	if err == nil {
		// Job exists — check status
		for _, cond := range existing.Status.Conditions {
			if cond.Type == batchv1.JobComplete && cond.Status == corev1.ConditionTrue {
				return true, nil
			}
			if cond.Type == batchv1.JobFailed && cond.Status == corev1.ConditionTrue {
				return false, fmt.Errorf("migration job failed: %s", cond.Message)
			}
		}
		return false, nil // still running
	}
	if !errors.IsNotFound(err) {
		return false, err
	}

	// Create the migration Job
	image := cf.Spec.Gateway.Image
	if image == "" {
		image = defaultGatewayImage
	}

	configMapName := nameFor(cf, "gateway-config")
	jwtSecretName := nameFor(cf, "jwt-secret")
	if cf.Spec.Auth.JWTSecretRef != nil {
		jwtSecretName = cf.Spec.Auth.JWTSecretRef.Name
	}
	dbSecretName := ""
	if cf.Spec.Database.Managed != nil {
		dbSecretName = nameFor(cf, "postgres-credentials")
	}

	backoffLimit := int32(3)
	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: cf.Namespace,
			Labels:    labels,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit: &backoffLimit,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					RestartPolicy: corev1.RestartPolicyOnFailure,
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: boolPtr(true),
					},
					Containers: []corev1.Container{{
						Name:  "migrate",
						Image: image,
						Command: []string{
							"python3", "-m", "alembic", "-c", "mcpgateway/alembic.ini", "upgrade", "head",
						},
						EnvFrom: []corev1.EnvFromSource{{
							ConfigMapRef: &corev1.ConfigMapEnvSource{
								LocalObjectReference: corev1.LocalObjectReference{Name: configMapName},
							},
						}},
						Env: gatewaySecretEnv(cf, jwtSecretName, dbSecretName),
						SecurityContext: &corev1.SecurityContext{
							AllowPrivilegeEscalation: boolPtr(false),
							RunAsUser:                int64Ptr(1001),
						},
					}},
				},
			},
		},
	}

	if err := controllerutil.SetControllerReference(cf, job, c.Scheme()); err != nil {
		return false, err
	}
	return false, c.Create(ctx, job)
}
