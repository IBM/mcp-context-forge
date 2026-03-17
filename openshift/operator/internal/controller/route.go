package controller

import (
	"context"
	"fmt"

	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

var routeGVR = schema.GroupVersionResource{
	Group: "route.openshift.io", Version: "v1", Resource: "routes",
}

// reconcileRoute creates or updates an OpenShift Route for the gateway.
// Uses unstructured to avoid a hard dependency on the OpenShift API types.
func reconcileRoute(ctx context.Context, c client.Client, cf *cfv1.ContextForge) (string, error) {
	route := cf.Spec.Gateway.Route
	if route == nil || !route.Enabled {
		return "", nil
	}

	name := nameFor(cf, "gateway")
	labels := commonLabels(cf, "gateway")

	// Determine the target service (nginx if enabled, otherwise gateway directly)
	targetService := nameFor(cf, "gateway")
	targetPort := "http"
	if cf.Spec.Nginx != nil && cf.Spec.Nginx.Enabled {
		targetService = nameFor(cf, "nginx")
	}

	tlsTermination := route.TLSTermination
	if tlsTermination == "" {
		tlsTermination = "edge"
	}

	// Build the Route as unstructured
	routeObj := &unstructured.Unstructured{}
	routeObj.SetGroupVersionKind(schema.GroupVersionKind{
		Group: "route.openshift.io", Version: "v1", Kind: "Route",
	})
	routeObj.SetName(name)
	routeObj.SetNamespace(cf.Namespace)

	// Check if it already exists
	existing := &unstructured.Unstructured{}
	existing.SetGroupVersionKind(routeObj.GroupVersionKind())
	err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: cf.Namespace}, existing)

	if errors.IsNotFound(err) {
		routeObj.SetLabels(labels)
		routeSpec := map[string]interface{}{
			"to": map[string]interface{}{
				"kind": "Service",
				"name": targetService,
			},
			"port": map[string]interface{}{
				"targetPort": targetPort,
			},
			"tls": map[string]interface{}{
				"termination": tlsTermination,
			},
		}
		if route.Host != "" {
			routeSpec["host"] = route.Host
		}
		if err := unstructured.SetNestedField(routeObj.Object, routeSpec, "spec"); err != nil {
			return "", fmt.Errorf("setting route spec: %w", err)
		}
		if err := controllerutil.SetControllerReference(cf, routeObj, c.Scheme()); err != nil {
			return "", err
		}
		if err := c.Create(ctx, routeObj); err != nil {
			return "", fmt.Errorf("creating route: %w", err)
		}
		// Read back to get the host
		if err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: cf.Namespace}, routeObj); err != nil {
			return "", nil // route created but can't read host yet
		}
	} else if err != nil {
		return "", err
	} else {
		routeObj = existing
	}

	// Extract the assigned host
	host, _, _ := unstructured.NestedString(routeObj.Object, "spec", "host")
	if host != "" {
		return fmt.Sprintf("https://%s", host), nil
	}

	// Try status.ingress[0].host
	ingress, _, _ := unstructured.NestedSlice(routeObj.Object, "status", "ingress")
	if len(ingress) > 0 {
		if ing, ok := ingress[0].(map[string]interface{}); ok {
			if h, ok := ing["host"].(string); ok && h != "" {
				return fmt.Sprintf("https://%s", h), nil
			}
		}
	}

	return "", nil
}

// routeAvailable checks whether the Route API is available on this cluster.
func routeAvailable(ctx context.Context, c client.Client) bool {
	routeList := &unstructured.UnstructuredList{}
	routeList.SetGroupVersionKind(schema.GroupVersionKind{
		Group: "route.openshift.io", Version: "v1", Kind: "RouteList",
	})
	// Try listing with limit=0 to see if the API exists
	err := c.List(ctx, routeList, &client.ListOptions{
		Namespace: metav1.NamespaceDefault,
		Limit:     0,
	})
	return err == nil
}
