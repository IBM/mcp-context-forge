package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ContextForgeSpec defines the desired state of a ContextForge cluster.
type ContextForgeSpec struct {
	// Gateway configures the main ContextForge API server.
	Gateway GatewaySpec `json:"gateway"`

	// Database configures PostgreSQL. Exactly one of Managed or External must be set.
	Database DatabaseSpec `json:"database"`

	// Redis configures the cache backend. Exactly one of Managed or External must be set.
	Redis RedisSpec `json:"redis"`

	// Nginx configures the reverse proxy tier.
	// +optional
	Nginx *NginxSpec `json:"nginx,omitempty"`

	// Auth configures authentication and authorization.
	Auth AuthSpec `json:"auth"`

	// Features toggles optional capabilities.
	// +optional
	Features *FeaturesSpec `json:"features,omitempty"`

	// Testing enables optional testing infrastructure.
	// +optional
	Testing *TestingSpec `json:"testing,omitempty"`
}

// ---------- Gateway ----------

type GatewaySpec struct {
	// Image is the container image for the gateway.
	// Defaults to the contextforge:latest ImageStream tag.
	// +optional
	Image string `json:"image,omitempty"`

	// Replicas is the number of gateway pods.
	// +kubebuilder:default=1
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// HTTPServer selects the HTTP runtime: "gunicorn" (default) or "granian".
	// +kubebuilder:validation:Enum=gunicorn;granian
	// +kubebuilder:default="gunicorn"
	// +optional
	HTTPServer string `json:"httpServer,omitempty"`

	// Workers sets the number of HTTP server worker processes.
	// +optional
	Workers *int32 `json:"workers,omitempty"`

	// Resources for the gateway pods.
	// +optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`

	// SessionPoolEnabled enables MCP session pooling.
	// +kubebuilder:default=true
	// +optional
	SessionPoolEnabled *bool `json:"sessionPoolEnabled,omitempty"`

	// StreamableHTTPMaxEventsPerStream sets the maximum events per streamable HTTP stream.
	// +optional
	StreamableHTTPMaxEventsPerStream *int32 `json:"streamableHTTPMaxEventsPerStream,omitempty"`

	// HTTPXMaxConnections sets the maximum number of HTTPX client connections.
	// +optional
	HTTPXMaxConnections *int32 `json:"httpxMaxConnections,omitempty"`

	// HTTPXMaxKeepaliveConnections sets the maximum number of HTTPX keepalive connections.
	// +optional
	HTTPXMaxKeepaliveConnections *int32 `json:"httpxMaxKeepaliveConnections,omitempty"`

	// Env is a list of additional environment variables to inject.
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`

	// Route controls OpenShift Route creation.
	// +optional
	Route *RouteSpec `json:"route,omitempty"`
}

type RouteSpec struct {
	// Enabled controls whether an OpenShift Route is created.
	// +kubebuilder:default=true
	Enabled bool `json:"enabled"`

	// Host overrides the auto-generated route hostname.
	// +optional
	Host string `json:"host,omitempty"`

	// TLSTermination sets the TLS termination type (edge, passthrough, reencrypt).
	// +kubebuilder:default="edge"
	// +optional
	TLSTermination string `json:"tlsTermination,omitempty"`
}

// ---------- Database ----------

type DatabaseSpec struct {
	// Managed deploys a PostgreSQL StatefulSet within the cluster.
	// +optional
	Managed *ManagedDatabaseSpec `json:"managed,omitempty"`

	// External connects to a pre-existing PostgreSQL instance.
	// +optional
	External *ExternalDatabaseSpec `json:"external,omitempty"`
}

type ManagedDatabaseSpec struct {
	// Image for the PostgreSQL container.
	// +kubebuilder:default="postgres:18"
	// +optional
	Image string `json:"image,omitempty"`

	// StorageSize is the PVC size for database data.
	// +kubebuilder:default="5Gi"
	// +optional
	StorageSize resource.Quantity `json:"storageSize,omitempty"`

	// StorageClassName overrides the default StorageClass.
	// +optional
	StorageClassName *string `json:"storageClassName,omitempty"`

	// Resources for the PostgreSQL pod.
	// +optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`
}

type ExternalDatabaseSpec struct {
	// URL is the full database connection string.
	// e.g. postgresql+psycopg://user:pass@host:5432/mcp
	// +optional
	URL string `json:"url,omitempty"`

	// SecretRef references a Secret containing the connection string under key "url".
	// +optional
	SecretRef *corev1.LocalObjectReference `json:"secretRef,omitempty"`
}

// ---------- Redis ----------

type RedisSpec struct {
	// Managed deploys a Redis instance within the cluster.
	// +optional
	Managed *ManagedRedisSpec `json:"managed,omitempty"`

	// External connects to a pre-existing Redis instance.
	// +optional
	External *ExternalRedisSpec `json:"external,omitempty"`
}

type ManagedRedisSpec struct {
	// Image for the Redis container.
	// +kubebuilder:default="redis:latest"
	// +optional
	Image string `json:"image,omitempty"`

	// Resources for the Redis pod.
	// +optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`
}

type ExternalRedisSpec struct {
	// URL is the Redis connection string. e.g. redis://host:6379/0
	// +optional
	URL string `json:"url,omitempty"`

	// SecretRef references a Secret containing the connection string under key "url".
	// +optional
	SecretRef *corev1.LocalObjectReference `json:"secretRef,omitempty"`
}

// ---------- Nginx ----------

type NginxSpec struct {
	// Enabled controls whether the nginx reverse proxy is deployed.
	// +kubebuilder:default=true
	Enabled bool `json:"enabled"`

	// Image for the nginx container.
	// +optional
	Image string `json:"image,omitempty"`

	// Resources for the nginx pod.
	// +optional
	Resources *corev1.ResourceRequirements `json:"resources,omitempty"`
}

// ---------- Auth ----------

type AuthSpec struct {
	// JWTSecretRef references a Secret containing the JWT signing key under key "secret".
	// If not set, the operator generates one.
	// +optional
	JWTSecretRef *corev1.LocalObjectReference `json:"jwtSecretRef,omitempty"`

	// AdminEmail is the platform admin email address.
	// +kubebuilder:default="admin@example.com"
	// +optional
	AdminEmail string `json:"adminEmail,omitempty"`

	// AdminPasswordRef references a Secret containing the admin password under key "password".
	// If not set, the operator generates one and stores it.
	// +optional
	AdminPasswordRef *corev1.LocalObjectReference `json:"adminPasswordRef,omitempty"`
}

// ---------- Features ----------

type FeaturesSpec struct {
	// UI enables the admin web UI.
	// +kubebuilder:default=true
	// +optional
	UI *bool `json:"ui,omitempty"`

	// AdminAPI enables the admin REST API.
	// +kubebuilder:default=true
	// +optional
	AdminAPI *bool `json:"adminApi,omitempty"`

	// A2A enables Agent-to-Agent protocol support.
	// +kubebuilder:default=true
	// +optional
	A2A *bool `json:"a2a,omitempty"`

	// Plugins configures the plugin framework.
	// +optional
	Plugins *PluginsSpec `json:"plugins,omitempty"`

	// Catalog enables the MCP catalog.
	// +kubebuilder:default=true
	// +optional
	Catalog *bool `json:"catalog,omitempty"`

	// RustRuntime configures the experimental Rust MCP runtime.
	// +optional
	RustRuntime *RustRuntimeSpec `json:"rustRuntime,omitempty"`
}

type PluginsSpec struct {
	// Enabled toggles the plugin framework on or off.
	// +kubebuilder:default=false
	// +optional
	Enabled *bool `json:"enabled,omitempty"`

	// ConfigFile is the path to the plugins configuration YAML inside the container.
	// Defaults to /plugins/config.yaml when gitSource is configured.
	// +optional
	ConfigFile string `json:"configFile,omitempty"`

	// ConfigMapRef references a ConfigMap whose key "config.yaml" is mounted as the
	// plugins configuration file. When set, this overrides the config.yaml from
	// gitSource and takes precedence over configFile.
	// +optional
	ConfigMapRef *corev1.LocalObjectReference `json:"configMapRef,omitempty"`

	// CanOverrideAuthHeaders allows plugins to override authentication headers.
	// +optional
	CanOverrideAuthHeaders *bool `json:"canOverrideAuthHeaders,omitempty"`

	// Image specifies a container image containing plugins. An initContainer
	// copies the image contents into a shared emptyDir mounted at /plugins.
	// Mutually exclusive with gitSource.
	// +optional
	Image string `json:"image,omitempty"`

	// GitSource clones a git repository into an emptyDir and mounts it as the
	// plugins directory. The operator resolves the ref to a commit SHA on each
	// reconciliation and triggers a rolling restart when it changes.
	// Mutually exclusive with image.
	// +optional
	GitSource *GitSourceSpec `json:"gitSource,omitempty"`

	// VolumeMounts defines additional volume mounts for plugin directories.
	// Used only when neither image nor gitSource is configured.
	// +optional
	VolumeMounts []corev1.VolumeMount `json:"volumeMounts,omitempty"`

	// Volumes defines additional volumes for plugin data.
	// Used only when neither image nor gitSource is configured.
	// +optional
	Volumes []corev1.Volume `json:"volumes,omitempty"`
}

type GitSourceSpec struct {
	// URL is the HTTPS clone URL of the git repository.
	URL string `json:"url"`

	// Ref is the branch, tag, or commit to checkout.
	// +kubebuilder:default="main"
	// +optional
	Ref string `json:"ref,omitempty"`

	// Directory is the subdirectory within the repo to use as the plugins root.
	// If empty, the entire repo root is used.
	// +optional
	Directory string `json:"directory,omitempty"`

	// SecretRef references a Secret containing git credentials.
	// Supported keys: "token" (Bearer token) or "username"+"password" (Basic auth).
	// +optional
	SecretRef *corev1.LocalObjectReference `json:"secretRef,omitempty"`
}

type RustRuntimeSpec struct {
	// Mode controls how the Rust runtime participates: off, shadow, edge, full.
	// +kubebuilder:validation:Enum=off;shadow;edge;full
	// +kubebuilder:default="off"
	Mode string `json:"mode,omitempty"`

	// LogPath sets the file path for Rust runtime logs inside the container.
	// +optional
	LogPath string `json:"logPath,omitempty"`
}

// ---------- Testing ----------

type TestingSpec struct {
	// Enabled deploys the testing infrastructure.
	Enabled bool `json:"enabled"`

	// FastTimeServer deploys the Go-based time tool server.
	// +optional
	FastTimeServer *bool `json:"fastTimeServer,omitempty"`

	// FastTestServer deploys the Rust-based test server.
	// +optional
	FastTestServer *bool `json:"fastTestServer,omitempty"`

	// SlowTimeServer deploys the latency-injecting time server.
	// +optional
	SlowTimeServer *bool `json:"slowTimeServer,omitempty"`

	// A2AEchoAgent deploys the A2A echo agent.
	// +optional
	A2AEchoAgent *bool `json:"a2aEchoAgent,omitempty"`

	// Locust configures Locust load testing infrastructure.
	// +optional
	Locust *LocustSpec `json:"locust,omitempty"`
}

type LocustSpec struct {
	// Enabled deploys the Locust load testing pods.
	// +optional
	Enabled *bool `json:"enabled,omitempty"`

	// Locustfile is the name of the locustfile to use.
	// +optional
	Locustfile string `json:"locustfile,omitempty"`

	// Env is a list of additional environment variables for Locust pods.
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`
}

// ---------- Status ----------

type ContextForgeStatus struct {
	// Phase is the overall cluster phase.
	// +optional
	Phase string `json:"phase,omitempty"`

	// Conditions represent the latest available observations.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// GatewayReady indicates the gateway deployment is available.
	// +optional
	GatewayReady bool `json:"gatewayReady,omitempty"`

	// DatabaseReady indicates the database is accepting connections.
	// +optional
	DatabaseReady bool `json:"databaseReady,omitempty"`

	// RedisReady indicates Redis is accepting connections.
	// +optional
	RedisReady bool `json:"redisReady,omitempty"`

	// MigrationComplete indicates the Alembic migration has run.
	// +optional
	MigrationComplete bool `json:"migrationComplete,omitempty"`

	// GatewayEndpoint is the externally reachable URL.
	// +optional
	GatewayEndpoint string `json:"gatewayEndpoint,omitempty"`

	// ObservedGeneration is the most recent generation observed.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Gateway",type=boolean,JSONPath=`.status.gatewayReady`
// +kubebuilder:printcolumn:name="Database",type=boolean,JSONPath=`.status.databaseReady`
// +kubebuilder:printcolumn:name="Redis",type=boolean,JSONPath=`.status.redisReady`
// +kubebuilder:printcolumn:name="Endpoint",type=string,JSONPath=`.status.gatewayEndpoint`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// ContextForge is the Schema for the contextforges API.
type ContextForge struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ContextForgeSpec   `json:"spec,omitempty"`
	Status ContextForgeStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ContextForgeList contains a list of ContextForge resources.
type ContextForgeList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ContextForge `json:"items"`
}
