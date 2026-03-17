package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

const (
	labelApp       = "app.kubernetes.io/name"
	labelInstance  = "app.kubernetes.io/instance"
	labelComponent = "app.kubernetes.io/component"
	labelManagedBy = "app.kubernetes.io/managed-by"
	managerName    = "contextforge-operator"
)

// commonLabels returns a standard set of labels for all managed resources.
func commonLabels(cf *cfv1.ContextForge, component string) map[string]string {
	return map[string]string{
		labelApp:       "contextforge",
		labelInstance:  cf.Name,
		labelComponent: component,
		labelManagedBy: managerName,
	}
}

// selectorLabels returns the subset of labels used in pod selectors.
func selectorLabels(cf *cfv1.ContextForge, component string) map[string]string {
	return map[string]string{
		labelApp:       "contextforge",
		labelInstance:  cf.Name,
		labelComponent: component,
	}
}

// nameFor returns a deterministic name for a sub-resource.
func nameFor(cf *cfv1.ContextForge, component string) string {
	return fmt.Sprintf("%s-%s", cf.Name, component)
}

// int32Ptr returns a pointer to an int32.
func int32Ptr(i int32) *int32 { return &i }

// boolVal returns the value of a *bool, or a default.
func boolVal(p *bool, def bool) bool {
	if p != nil {
		return *p
	}
	return def
}

// createOrUpdate is a helper that wraps controllerutil.CreateOrUpdate with
// standard ownership and logging.
func createOrUpdate(
	ctx context.Context,
	c client.Client,
	cf *cfv1.ContextForge,
	obj client.Object,
	mutate func() error,
) error {
	obj.SetNamespace(cf.Namespace)
	result, err := controllerutil.CreateOrUpdate(ctx, c, obj, func() error {
		if err := controllerutil.SetControllerReference(cf, obj, c.Scheme()); err != nil {
			return err
		}
		return mutate()
	})
	if err != nil {
		return fmt.Errorf("failed to %s %s/%s: %w", result, obj.GetObjectKind().GroupVersionKind().Kind, obj.GetName(), err)
	}
	return nil
}

// isDeploymentAvailable checks if a Deployment has at least one available replica.
func isDeploymentAvailable(ctx context.Context, c client.Client, namespace, name string) bool {
	dep := &appsv1.Deployment{}
	if err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, dep); err != nil {
		return false
	}
	return dep.Status.AvailableReplicas > 0
}

// isStatefulSetReady checks if a StatefulSet has all replicas ready.
func isStatefulSetReady(ctx context.Context, c client.Client, namespace, name string) bool {
	ss := &appsv1.StatefulSet{}
	if err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, ss); err != nil {
		return false
	}
	return ss.Status.ReadyReplicas > 0 && ss.Status.ReadyReplicas == *ss.Spec.Replicas
}

// ensureSecret creates a Secret if it doesn't already exist. Does not update existing secrets.
func ensureSecret(ctx context.Context, c client.Client, cf *cfv1.ContextForge, name string, data map[string][]byte) error {
	secret := &corev1.Secret{}
	err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: cf.Namespace}, secret)
	if err == nil {
		return nil // already exists
	}
	if !errors.IsNotFound(err) {
		return err
	}
	secret = &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: cf.Namespace,
			Labels:    commonLabels(cf, "secret"),
		},
		Data: data,
	}
	if err := controllerutil.SetControllerReference(cf, secret, c.Scheme()); err != nil {
		return err
	}
	return c.Create(ctx, secret)
}
