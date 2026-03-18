package controller

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	cfv1 "github.com/IBM/mcp-context-forge/operator/api/v1alpha1"
)

// ContextForgeReconciler reconciles a ContextForge object.
type ContextForgeReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=contextforge.io,resources=contextforges,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=contextforge.io,resources=contextforges/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=contextforge.io,resources=contextforges/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments;statefulsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create;delete
// +kubebuilder:rbac:groups="",resources=services;configmaps;secrets;persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=route.openshift.io,resources=routes,verbs=get;list;watch;create;update;patch;delete

func (r *ContextForgeReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	cf := &cfv1.ContextForge{}
	if err := r.Get(ctx, req.NamespacedName, cf); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	logger.Info("reconciling ContextForge", "name", cf.Name)

	// Initialize status
	cf.Status.ObservedGeneration = cf.Generation
	cf.Status.Phase = "Reconciling"
	defer func() {
		if err := r.Status().Update(ctx, cf); err != nil {
			logger.Error(err, "failed to update status")
		}
	}()

	// Step 1: Ensure JWT secret exists
	if err := r.ensureJWTSecret(ctx, cf); err != nil {
		return r.setFailed(cf, "JWTSecretFailed", err)
	}

	// Step 2: Reconcile database (PostgreSQL)
	dbURL, dbSecretName, err := reconcileDatabaseFull(ctx, r.Client, cf)
	if err != nil {
		return r.setFailed(cf, "DatabaseFailed", err)
	}
	cf.Status.DatabaseReady = r.isDatabaseReady(ctx, cf)
	setCondition(cf, "DatabaseReady", cf.Status.DatabaseReady, "Database reconciled")

	if !cf.Status.DatabaseReady {
		logger.Info("waiting for database to become ready")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// Step 3: Reconcile Redis
	redisURL, err := reconcileRedis(ctx, r.Client, cf)
	if err != nil {
		return r.setFailed(cf, "RedisFailed", err)
	}
	cf.Status.RedisReady = r.isRedisReady(ctx, cf)
	setCondition(cf, "RedisReady", cf.Status.RedisReady, "Redis reconciled")

	if !cf.Status.RedisReady {
		logger.Info("waiting for Redis to become ready")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// Step 4: Database migration
	migrationDone, err := reconcileMigration(ctx, r.Client, cf)
	if err != nil {
		return r.setFailed(cf, "MigrationFailed", err)
	}
	cf.Status.MigrationComplete = migrationDone
	setCondition(cf, "MigrationComplete", migrationDone, "Database migration")

	if !migrationDone {
		logger.Info("waiting for database migration to complete")
		return ctrl.Result{RequeueAfter: 15 * time.Second}, nil
	}

	// Step 5: Resolve plugins git commit SHA (if configured)
	var pluginsGitSHA string
	if cf.Spec.Features != nil && cf.Spec.Features.Plugins != nil && cf.Spec.Features.Plugins.GitSource != nil {
		sha, err := resolveGitCommitSHA(ctx, r.Client, cf.Spec.Features.Plugins.GitSource, cf.Namespace)
		if err != nil {
			logger.Error(err, "failed to resolve plugins git SHA, deployment will proceed without SHA annotation")
		} else {
			pluginsGitSHA = sha
		}
	}

	// Step 6: Gateway
	if err := reconcileGateway(ctx, r.Client, cf, dbURL, dbSecretName, redisURL, pluginsGitSHA); err != nil {
		return r.setFailed(cf, "GatewayFailed", err)
	}
	cf.Status.GatewayReady = isDeploymentAvailable(ctx, r.Client, cf.Namespace, nameFor(cf, "gateway"))
	setCondition(cf, "GatewayReady", cf.Status.GatewayReady, "Gateway deployment")

	// Step 6: Nginx
	if err := reconcileNginx(ctx, r.Client, cf); err != nil {
		return r.setFailed(cf, "NginxFailed", err)
	}

	// Step 7: OpenShift Route (if available)
	if routeAvailable(ctx, r.Client) {
		endpoint, err := reconcileRoute(ctx, r.Client, cf)
		if err != nil {
			logger.Error(err, "route reconciliation failed (non-fatal)")
		}
		cf.Status.GatewayEndpoint = endpoint
	}

	// Final status
	if cf.Status.GatewayReady && cf.Status.DatabaseReady && cf.Status.RedisReady {
		cf.Status.Phase = "Running"
	} else {
		cf.Status.Phase = "Progressing"
		return ctrl.Result{RequeueAfter: 15 * time.Second}, nil
	}

	logger.Info("reconciliation complete", "phase", cf.Status.Phase, "endpoint", cf.Status.GatewayEndpoint)
	return ctrl.Result{RequeueAfter: 60 * time.Second}, nil
}

func (r *ContextForgeReconciler) ensureJWTSecret(ctx context.Context, cf *cfv1.ContextForge) error {
	if cf.Spec.Auth.JWTSecretRef != nil {
		return nil // user-provided
	}
	name := nameFor(cf, "jwt-secret")
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return err
	}
	return ensureSecret(ctx, r.Client, cf, name, map[string][]byte{
		"secret": []byte(hex.EncodeToString(key)),
	})
}

func (r *ContextForgeReconciler) isDatabaseReady(ctx context.Context, cf *cfv1.ContextForge) bool {
	if cf.Spec.Database.External != nil {
		return true // trust external DBs
	}
	return isStatefulSetReady(ctx, r.Client, cf.Namespace, nameFor(cf, "postgres"))
}

func (r *ContextForgeReconciler) isRedisReady(ctx context.Context, cf *cfv1.ContextForge) bool {
	if cf.Spec.Redis.External != nil {
		return true
	}
	return isDeploymentAvailable(ctx, r.Client, cf.Namespace, nameFor(cf, "redis"))
}

func (r *ContextForgeReconciler) setFailed(cf *cfv1.ContextForge, reason string, err error) (ctrl.Result, error) {
	cf.Status.Phase = "Failed"
	setCondition(cf, reason, false, err.Error())
	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

func setCondition(cf *cfv1.ContextForge, condType string, status bool, message string) {
	s := metav1.ConditionFalse
	if status {
		s = metav1.ConditionTrue
	}
	meta.SetStatusCondition(&cf.Status.Conditions, metav1.Condition{
		Type:               condType,
		Status:             s,
		Reason:             condType,
		Message:            message,
		ObservedGeneration: cf.Generation,
	})
}

// SetupWithManager sets up the controller with the Manager.
func (r *ContextForgeReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&cfv1.ContextForge{}).
		Owns(&appsv1.Deployment{}).
		Owns(&appsv1.StatefulSet{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{}).
		Owns(&corev1.Secret{}).
		Owns(&batchv1.Job{}).
		Named("contextforge").
		Complete(r)
}
