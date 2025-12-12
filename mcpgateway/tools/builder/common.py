# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/common.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Common utilities shared between Dagger and plain Python implementations.

This module contains shared functionality to avoid code duplication between
the Dagger-based (dagger_module.py) and plain Python (plain_deploy.py)
implementations of the MCP Stack deployment system.

Shared functions:
- load_config: Load and parse YAML configuration file
- generate_plugin_config: Generate plugins-config.yaml for gateway from mcp-stack.yaml
- generate_kubernetes_manifests: Generate Kubernetes deployment manifests
- generate_compose_manifests: Generate Docker Compose manifest
- copy_env_template: Copy .env.template from plugin repo to env.d/ directory
- handle_registry_operations: Tag and push images to container registry
- get_docker_compose_command: Detect available docker compose command
- run_compose: Run docker compose with error handling
- deploy_compose: Deploy using docker compose up -d
- verify_compose: Verify deployment with docker compose ps
- destroy_compose: Destroy deployment with docker compose down -v
- deploy_kubernetes: Deploy to Kubernetes using kubectl
- verify_kubernetes: Verify Kubernetes deployment health
- destroy_kubernetes: Destroy Kubernetes deployment with kubectl delete
"""

# Standard
import base64
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404
from typing import List

# Third-Party
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
import yaml

# First-Party
from mcpgateway.tools.builder.schema import MCPStackConfig

console = Console()


def get_deploy_dir() -> Path:
    """Get deployment directory from environment variable or default.

    Checks MCP_DEPLOY_DIR environment variable, defaults to './deploy'.

    Returns:
        Path to deployment directory

    Examples:
        >>> # Test with default value (when MCP_DEPLOY_DIR is not set)
        >>> import os
        >>> old_value = os.environ.pop("MCP_DEPLOY_DIR", None)
        >>> result = get_deploy_dir()
        >>> isinstance(result, Path)
        True
        >>> str(result)
        'deploy'

        >>> # Test with custom environment variable
        >>> os.environ["MCP_DEPLOY_DIR"] = "/custom/deploy"
        >>> result = get_deploy_dir()
        >>> str(result)
        '/custom/deploy'

        >>> # Cleanup: restore original value
        >>> if old_value is not None:
        ...     os.environ["MCP_DEPLOY_DIR"] = old_value
        ... else:
        ...     _ = os.environ.pop("MCP_DEPLOY_DIR", None)
    """
    deploy_dir = os.environ.get("MCP_DEPLOY_DIR", "./deploy")
    return Path(deploy_dir)


def load_config(config_file: str) -> MCPStackConfig:
    """Load and parse YAML configuration file into validated Pydantic model.

    Args:
        config_file: Path to mcp-stack.yaml configuration file

    Returns:
        Validated MCPStackConfig Pydantic model

    Raises:
        FileNotFoundError: If configuration file doesn't exist
        ValidationError: If configuration validation fails

    Examples:
        >>> # Test with non-existent file
        >>> try:
        ...     load_config("/nonexistent/path/config.yaml")
        ... except FileNotFoundError as e:
        ...     "Configuration file not found" in str(e)
        True

        >>> # Test that function returns MCPStackConfig type
        >>> from mcpgateway.tools.builder.schema import MCPStackConfig
        >>> # Actual file loading would require a real file:
        >>> # config = load_config("mcp-stack.yaml")
        >>> # assert isinstance(config, MCPStackConfig)
    """
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    with open(config_path, encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    # Validate and return Pydantic model
    return MCPStackConfig.model_validate(config_dict)


def generate_plugin_config(config: MCPStackConfig, output_dir: Path, verbose: bool = False) -> Path:
    """Generate plugin config.yaml for gateway from mcp-stack.yaml.

    This function is shared between Dagger and plain Python implementations
    to avoid code duplication.

    Args:
        config: Validated MCPStackConfig Pydantic model
        output_dir: Output directory for generated config
        verbose: Print verbose output

    Returns:
        Path to generated plugins-config.yaml file

    Raises:
        FileNotFoundError: If template directory not found

    Examples:
        >>> from pathlib import Path
        >>> from mcpgateway.tools.builder.schema import MCPStackConfig, DeploymentConfig, GatewayConfig
        >>> import tempfile
        >>> # Test with minimal config
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     output = Path(tmpdir)
        ...     config = MCPStackConfig(
        ...         deployment=DeploymentConfig(type="compose"),
        ...         gateway=GatewayConfig(image="test:latest"),
        ...         plugins=[]
        ...     )
        ...     result = generate_plugin_config(config, output, verbose=False)
        ...     result.name
        'plugins-config.yaml'

        >>> # Test return type
        >>> # result_path = generate_plugin_config(config, output_dir)
        >>> # isinstance(result_path, Path)
        >>> # True
    """

    deployment_type = config.deployment.type
    plugins = config.plugins

    # Load template
    template_dir = Path(__file__).parent / "templates"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # YAML files should not use HTML autoescape
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)  # nosec B701
    template = env.get_template("plugins-config.yaml.j2")

    # Prepare plugin data with computed URLs
    plugin_data = []
    for plugin in plugins:
        plugin_name = plugin.name
        port = plugin.port or 8000

        # Determine URL based on deployment type
        if deployment_type == "compose":
            # Use container hostname (lowercase)
            hostname = plugin_name.lower()
            # Use HTTPS if mTLS is enabled
            protocol = "https" if plugin.mtls_enabled else "http"
            url = f"{protocol}://{hostname}:{port}/mcp"
        else:  # kubernetes
            # Use Kubernetes service DNS
            namespace = config.deployment.namespace or "mcp-gateway"
            service_name = f"mcp-plugin-{plugin_name.lower()}"
            protocol = "https" if plugin.mtls_enabled else "http"
            url = f"{protocol}://{service_name}.{namespace}.svc:{port}/mcp"

        # Build plugin entry with computed URL
        plugin_entry = {
            "name": plugin_name,
            "port": port,
            "url": url,
        }

        # Merge plugin_overrides (client-side config only, excludes 'config')
        # Allowed client-side fields that plugin manager uses
        if plugin.plugin_overrides:
            overrides = plugin.plugin_overrides
            allowed_fields = ["priority", "mode", "description", "version", "author", "hooks", "tags", "conditions"]
            for field in allowed_fields:
                if field in overrides:
                    plugin_entry[field] = overrides[field]

        plugin_data.append(plugin_entry)

    # Render template
    rendered = template.render(plugins=plugin_data)

    # Write config file
    config_path = output_dir / "plugins-config.yaml"
    config_path.write_text(rendered)

    if verbose:
        print(f"✓ Plugin config generated: {config_path}")

    return config_path


def generate_kubernetes_manifests(config: MCPStackConfig, output_dir: Path, verbose: bool = False) -> None:
    """Generate Kubernetes manifests from configuration.

    Args:
        config: Validated MCPStackConfig Pydantic model
        output_dir: Output directory for manifests
        verbose: Print verbose output

    Raises:
        FileNotFoundError: If template directory not found

    Examples:
        >>> from pathlib import Path
        >>> import inspect
        >>> # Test function signature
        >>> sig = inspect.signature(generate_kubernetes_manifests)
        >>> list(sig.parameters.keys())
        ['config', 'output_dir', 'verbose']

        >>> # Test that verbose parameter has default
        >>> sig.parameters['verbose'].default
        False

        >>> # Actual usage requires valid config and templates:
        >>> # from mcpgateway.tools.builder.schema import MCPStackConfig
        >>> # generate_kubernetes_manifests(config, Path("./output"))
    """

    # Load templates
    template_dir = Path(__file__).parent / "templates" / "kubernetes"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Auto-detect and assign env files if not specified
    _auto_detect_env_files(config, output_dir, verbose=verbose)

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)  # nosec B701

    # Generate namespace
    namespace = config.deployment.namespace or "mcp-gateway"

    # Generate mTLS certificate resources if enabled
    gateway_mtls = config.gateway.mtls_enabled if config.gateway.mtls_enabled is not None else True
    cert_config = config.certificates
    use_cert_manager = cert_config.use_cert_manager if cert_config else False

    if gateway_mtls:
        if use_cert_manager:
            # Generate cert-manager Certificate CRDs
            cert_manager_template = env.get_template("cert-manager-certificates.yaml.j2")

            # Calculate duration and renewBefore in hours
            validity_days = cert_config.validity_days or 825
            duration_hours = validity_days * 24
            # Renew at 2/3 of lifetime (cert-manager default)
            renew_before_hours = int(duration_hours * 2 / 3)

            # Prepare certificate data
            cert_data = {
                "namespace": namespace,
                "gateway_name": "mcpgateway",
                "issuer_name": cert_config.cert_manager_issuer or "mcp-ca-issuer",
                "issuer_kind": cert_config.cert_manager_kind or "Issuer",
                "duration": duration_hours,
                "renew_before": renew_before_hours,
                "plugins": [],
            }

            # Add plugins with mTLS enabled
            for plugin in config.plugins:
                if plugin.mtls_enabled if plugin.mtls_enabled is not None else True:
                    cert_data["plugins"].append({"name": f"mcp-plugin-{plugin.name.lower()}"})

            # Generate cert-manager certificates manifest
            cert_manager_manifest = cert_manager_template.render(**cert_data)
            (output_dir / "cert-manager-certificates.yaml").write_text(cert_manager_manifest)
            if verbose:
                print("  ✓ cert-manager Certificate CRDs manifest generated")

        else:
            # Generate traditional certificate secrets (backward compatibility)
            cert_secrets_template = env.get_template("cert-secrets.yaml.j2")

            # Prepare certificate data
            cert_data = {"namespace": namespace, "gateway_name": "mcpgateway", "plugins": []}

            # Read and encode CA certificate
            ca_cert_path = Path("certs/mcp/ca/ca.crt")
            if ca_cert_path.exists():
                cert_data["ca_cert_b64"] = base64.b64encode(ca_cert_path.read_bytes()).decode("utf-8")
            else:
                if verbose:
                    print(f"[yellow]Warning: CA certificate not found at {ca_cert_path}[/yellow]")

            # Read and encode gateway certificates
            gateway_cert_path = Path("certs/mcp/gateway/client.crt")
            gateway_key_path = Path("certs/mcp/gateway/client.key")
            if gateway_cert_path.exists() and gateway_key_path.exists():
                cert_data["gateway_cert_b64"] = base64.b64encode(gateway_cert_path.read_bytes()).decode("utf-8")
                cert_data["gateway_key_b64"] = base64.b64encode(gateway_key_path.read_bytes()).decode("utf-8")
            else:
                if verbose:
                    print("[yellow]Warning: Gateway certificates not found[/yellow]")

            # Read and encode plugin certificates
            for plugin in config.plugins:
                if plugin.mtls_enabled if plugin.mtls_enabled is not None else True:
                    plugin_name = plugin.name
                    plugin_cert_path = Path(f"certs/mcp/plugins/{plugin_name}/server.crt")
                    plugin_key_path = Path(f"certs/mcp/plugins/{plugin_name}/server.key")

                    if plugin_cert_path.exists() and plugin_key_path.exists():
                        cert_data["plugins"].append(
                            {
                                "name": f"mcp-plugin-{plugin_name.lower()}",
                                "cert_b64": base64.b64encode(plugin_cert_path.read_bytes()).decode("utf-8"),
                                "key_b64": base64.b64encode(plugin_key_path.read_bytes()).decode("utf-8"),
                            }
                        )
                    else:
                        if verbose:
                            print(f"[yellow]Warning: Plugin {plugin_name} certificates not found[/yellow]")

            # Generate certificate secrets manifest
            if "ca_cert_b64" in cert_data:
                cert_secrets_manifest = cert_secrets_template.render(**cert_data)
                (output_dir / "cert-secrets.yaml").write_text(cert_secrets_manifest)
                if verbose:
                    print("  ✓ mTLS certificate secrets manifest generated")

    # Generate infrastructure manifests (postgres, redis) if enabled
    infrastructure = config.infrastructure

    # PostgreSQL
    if infrastructure and infrastructure.postgres and infrastructure.postgres.enabled:
        postgres_config = infrastructure.postgres
        postgres_template = env.get_template("postgres.yaml.j2")
        postgres_manifest = postgres_template.render(
            namespace=namespace,
            image=postgres_config.image or "quay.io/sclorg/postgresql-15-c9s:latest",
            database=postgres_config.database or "mcp",
            user=postgres_config.user or "postgres",
            password=postgres_config.password or "mysecretpassword",
            storage_size=postgres_config.storage_size or "10Gi",
            storage_class=postgres_config.storage_class,
        )
        (output_dir / "postgres-deployment.yaml").write_text(postgres_manifest)
        if verbose:
            print("  ✓ PostgreSQL deployment manifest generated")

    # Redis
    if infrastructure and infrastructure.redis and infrastructure.redis.enabled:
        redis_config = infrastructure.redis
        redis_template = env.get_template("redis.yaml.j2")
        redis_manifest = redis_template.render(namespace=namespace, image=redis_config.image or "redis:latest")
        (output_dir / "redis-deployment.yaml").write_text(redis_manifest)
        if verbose:
            print("  ✓ Redis deployment manifest generated")

    # Generate plugins ConfigMap if plugins are configured
    if config.plugins and len(config.plugins) > 0:
        configmap_template = env.get_template("plugins-configmap.yaml.j2")
        # Read the generated plugins-config.yaml file
        plugins_config_path = output_dir / "plugins-config.yaml"
        if plugins_config_path.exists():
            plugins_config_content = plugins_config_path.read_text()
            configmap_manifest = configmap_template.render(namespace=namespace, plugins_config=plugins_config_content)
            (output_dir / "plugins-configmap.yaml").write_text(configmap_manifest)
            if verbose:
                print("  ✓ Plugins ConfigMap manifest generated")

    # Generate gateway deployment
    gateway_template = env.get_template("deployment.yaml.j2")
    # Convert Pydantic model to dict for template rendering
    gateway_dict = config.gateway.model_dump(exclude_none=True)
    gateway_dict["name"] = "mcpgateway"
    gateway_dict["namespace"] = namespace
    gateway_dict["has_plugins"] = config.plugins and len(config.plugins) > 0

    # Update image to use full registry path if registry is enabled
    if config.gateway.registry and config.gateway.registry.enabled:
        base_image_name = config.gateway.image.split(":")[0].split("/")[-1]
        image_version = config.gateway.image.split(":")[-1] if ":" in config.gateway.image else "latest"
        gateway_dict["image"] = f"{config.gateway.registry.url}/{config.gateway.registry.namespace}/{base_image_name}:{image_version}"
        # Set imagePullPolicy from registry config
        if config.gateway.registry.image_pull_policy:
            gateway_dict["image_pull_policy"] = config.gateway.registry.image_pull_policy

    # Add DATABASE_URL and REDIS_URL to gateway environment if infrastructure is enabled
    if "env_vars" not in gateway_dict:
        gateway_dict["env_vars"] = {}

    # Enable plugins if any are configured
    if config.plugins and len(config.plugins) > 0:
        gateway_dict["env_vars"]["PLUGINS_ENABLED"] = "true"
        gateway_dict["env_vars"]["PLUGIN_CONFIG_FILE"] = "/app/config/plugins.yaml"

    # Add init containers to wait for infrastructure services
    init_containers = []

    if infrastructure and infrastructure.postgres and infrastructure.postgres.enabled:
        postgres = infrastructure.postgres
        db_user = postgres.user or "postgres"
        db_password = postgres.password or "mysecretpassword"
        db_name = postgres.database or "mcp"
        gateway_dict["env_vars"]["DATABASE_URL"] = f"postgresql://{db_user}:{db_password}@postgres:5432/{db_name}"

        # Add init container to wait for PostgreSQL
        init_containers.append({"name": "wait-for-postgres", "image": "busybox:1.36", "command": ["sh", "-c", "until nc -z postgres 5432; do echo waiting for postgres; sleep 2; done"]})

    if infrastructure and infrastructure.redis and infrastructure.redis.enabled:
        gateway_dict["env_vars"]["REDIS_URL"] = "redis://redis:6379/0"

        # Add init container to wait for Redis
        init_containers.append({"name": "wait-for-redis", "image": "busybox:1.36", "command": ["sh", "-c", "until nc -z redis 6379; do echo waiting for redis; sleep 2; done"]})

    # Add init containers to wait for plugins to be ready
    if config.plugins and len(config.plugins) > 0:
        for plugin in config.plugins:
            plugin_service_name = f"mcp-plugin-{plugin.name.lower()}"
            plugin_port = plugin.port or 8000
            # Wait for plugin service to be available
            init_containers.append(
                {
                    "name": f"wait-for-{plugin.name.lower()}",
                    "image": "busybox:1.36",
                    "command": ["sh", "-c", f"until nc -z {plugin_service_name} {plugin_port}; do echo waiting for {plugin_service_name}; sleep 2; done"],
                }
            )

    if init_containers:
        gateway_dict["init_containers"] = init_containers

    gateway_manifest = gateway_template.render(**gateway_dict)
    (output_dir / "gateway-deployment.yaml").write_text(gateway_manifest)

    # Generate OpenShift Route if configured
    if config.deployment.openshift and config.deployment.openshift.create_routes:
        route_template = env.get_template("route.yaml.j2")
        openshift_config = config.deployment.openshift

        # Auto-detect OpenShift apps domain if not specified
        openshift_domain = openshift_config.domain
        if not openshift_domain:
            try:
                # Try to get domain from OpenShift cluster info
                result = subprocess.run(
                    ["kubectl", "get", "ingresses.config.openshift.io", "cluster", "-o", "jsonpath={.spec.domain}"], capture_output=True, text=True, check=False
                )  # nosec B603, B607
                if result.returncode == 0 and result.stdout.strip():
                    openshift_domain = result.stdout.strip()
                    if verbose:
                        console.print(f"[dim]Auto-detected OpenShift domain: {openshift_domain}[/dim]")
                else:
                    # Fallback to common OpenShift Local domain
                    openshift_domain = "apps-crc.testing"
                    if verbose:
                        console.print(f"[yellow]Could not auto-detect OpenShift domain, using default: {openshift_domain}[/yellow]")
            except Exception:
                # Fallback to common OpenShift Local domain
                openshift_domain = "apps-crc.testing"
                if verbose:
                    console.print(f"[yellow]Could not auto-detect OpenShift domain, using default: {openshift_domain}[/yellow]")

        route_manifest = route_template.render(namespace=namespace, openshift_domain=openshift_domain, tls_termination=openshift_config.tls_termination)
        (output_dir / "gateway-route.yaml").write_text(route_manifest)
        if verbose:
            print("  ✓ OpenShift Route manifest generated")

    # Generate plugin deployments
    for plugin in config.plugins:
        # Convert Pydantic model to dict for template rendering
        plugin_dict = plugin.model_dump(exclude_none=True)
        plugin_dict["name"] = f"mcp-plugin-{plugin.name.lower()}"
        plugin_dict["namespace"] = namespace

        # Update image to use full registry path if registry is enabled
        if plugin.registry and plugin.registry.enabled:
            base_image_name = plugin.image.split(":")[0].split("/")[-1]
            image_version = plugin.image.split(":")[-1] if ":" in plugin.image else "latest"
            plugin_dict["image"] = f"{plugin.registry.url}/{plugin.registry.namespace}/{base_image_name}:{image_version}"
            # Set imagePullPolicy from registry config
            if plugin.registry.image_pull_policy:
                plugin_dict["image_pull_policy"] = plugin.registry.image_pull_policy

        plugin_manifest = gateway_template.render(**plugin_dict)
        (output_dir / f"plugin-{plugin.name.lower()}-deployment.yaml").write_text(plugin_manifest)

    if verbose:
        print(f"✓ Kubernetes manifests generated in {output_dir}")


def generate_compose_manifests(config: MCPStackConfig, output_dir: Path, verbose: bool = False) -> None:
    """Generate Docker Compose manifest from configuration.

    Args:
        config: Validated MCPStackConfig Pydantic model
        output_dir: Output directory for manifests
        verbose: Print verbose output

    Raises:
        FileNotFoundError: If template directory not found

    Examples:
        >>> from pathlib import Path
        >>> import inspect
        >>> # Test function signature
        >>> sig = inspect.signature(generate_compose_manifests)
        >>> list(sig.parameters.keys())
        ['config', 'output_dir', 'verbose']

        >>> # Test default parameters
        >>> sig.parameters['verbose'].default
        False

        >>> # Actual execution requires templates and config:
        >>> # from mcpgateway.tools.builder.schema import MCPStackConfig
        >>> # generate_compose_manifests(config, Path("./output"))
    """

    # Load templates
    template_dir = Path(__file__).parent / "templates" / "compose"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Auto-detect and assign env files if not specified
    _auto_detect_env_files(config, output_dir, verbose=verbose)

    # Auto-assign host_ports if expose_port is true but host_port not specified
    next_host_port = 8000
    for plugin in config.plugins:
        # Port defaults are handled by Pydantic defaults in schema

        # Auto-assign host_port if expose_port is true
        if plugin.expose_port and not plugin.host_port:
            plugin.host_port = next_host_port  # type: ignore
            next_host_port += 1

    # Compute relative certificate paths (from output_dir to project root certs/)
    # Certificates are at: ./certs/mcp/...
    # Output dir is at: ./deploy/manifests/
    # So relative path is: ../../certs/mcp/...
    certs_base = Path.cwd() / "certs"
    certs_rel_base = os.path.relpath(certs_base, output_dir)

    # Add computed cert paths to context for template
    cert_paths = {
        "certs_base": certs_rel_base,
        "gateway_cert_dir": os.path.join(certs_rel_base, "mcp/gateway"),
        "ca_cert_file": os.path.join(certs_rel_base, "mcp/ca/ca.crt"),
        "plugins_cert_base": os.path.join(certs_rel_base, "mcp/plugins"),
    }

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)  # nosec B701

    # Generate compose file
    compose_template = env.get_template("docker-compose.yaml.j2")
    # Convert Pydantic model to dict for template rendering
    config_dict = config.model_dump(exclude_none=True)
    compose_manifest = compose_template.render(**config_dict, cert_paths=cert_paths)
    (output_dir / "docker-compose.yaml").write_text(compose_manifest)

    if verbose:
        print(f"✓ Compose manifest generated in {output_dir}")


def _auto_detect_env_files(config: MCPStackConfig, output_dir: Path, verbose: bool = False) -> None:
    """Auto-detect and assign env files if not explicitly specified.

    If env_file is not specified in the config, check if {deploy_dir}/env/.env.{name}
    exists and use it. Warn the user when auto-detection is used.

    Args:
        config: MCPStackConfig Pydantic model (modified in-place via attribute assignment)
        output_dir: Output directory where manifests will be generated (for relative paths)
        verbose: Print verbose output

    Examples:
        >>> from pathlib import Path
        >>> from mcpgateway.tools.builder.schema import MCPStackConfig, DeploymentConfig, GatewayConfig
        >>> import tempfile
        >>> # Test function modifies config in place
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     output = Path(tmpdir)
        ...     config = MCPStackConfig(
        ...         deployment=DeploymentConfig(type="compose"),
        ...         gateway=GatewayConfig(image="test:latest"),
        ...         plugins=[]
        ...     )
        ...     # Function modifies config if env files exist
        ...     _auto_detect_env_files(config, output, verbose=False)
        ...     # Config object is modified in place
        ...     isinstance(config, MCPStackConfig)
        True

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(_auto_detect_env_files)
        >>> 'verbose' in sig.parameters
        True
    """
    deploy_dir = get_deploy_dir()
    env_dir = deploy_dir / "env"

    # Check gateway - since we need to modify the model, we access env_file directly
    # Note: Pydantic models allow attribute assignment after creation
    if not hasattr(config.gateway, "env_file") or not config.gateway.env_file:
        gateway_env = env_dir / ".env.gateway"
        if gateway_env.exists():
            # Make path relative to output_dir (where docker-compose.yaml will be)
            relative_path = os.path.relpath(gateway_env, output_dir)
            config.gateway.env_file = relative_path  # type: ignore
            print(f"⚠ Auto-detected env file: {gateway_env}")
            if verbose:
                print("   (Gateway env_file not specified in config)")

    # Check plugins
    for plugin in config.plugins:
        plugin_name = plugin.name
        if not hasattr(plugin, "env_file") or not plugin.env_file:
            plugin_env = env_dir / f".env.{plugin_name}"
            if plugin_env.exists():
                # Make path relative to output_dir (where docker-compose.yaml will be)
                relative_path = os.path.relpath(plugin_env, output_dir)
                plugin.env_file = relative_path  # type: ignore
                print(f"⚠ Auto-detected env file: {plugin_env}")
                if verbose:
                    print(f"   (Plugin {plugin_name} env_file not specified in config)")


def copy_env_template(plugin_name: str, plugin_build_dir: Path, verbose: bool = False) -> None:
    """Copy .env.template from plugin repo to {deploy_dir}/env/ directory.

    Uses MCP_DEPLOY_DIR environment variable if set, defaults to './deploy'.
    This function is shared between Dagger and plain Python implementations.

    Args:
        plugin_name: Name of the plugin
        plugin_build_dir: Path to plugin build directory (contains .env.template)
        verbose: Print verbose output

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> import os
        >>> # Test with non-existent template (should return early)
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     build_dir = Path(tmpdir)
        ...     # No .env.template exists, function returns early
        ...     copy_env_template("test-plugin", build_dir, verbose=False)

        >>> # Test directory creation
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     os.environ["MCP_DEPLOY_DIR"] = tmpdir
        ...     build_dir = Path(tmpdir) / "build"
        ...     build_dir.mkdir()
        ...     template = build_dir / ".env.template"
        ...     _ = template.write_text("TEST=value")
        ...     copy_env_template("test", build_dir, verbose=False)
        ...     env_file = Path(tmpdir) / "env" / ".env.test"
        ...     env_file.exists()
        True

        >>> # Cleanup
        >>> _ = os.environ.pop("MCP_DEPLOY_DIR", None)
    """
    # Create {deploy_dir}/env directory if it doesn't exist
    deploy_dir = get_deploy_dir()
    env_dir = deploy_dir / "env"
    env_dir.mkdir(parents=True, exist_ok=True)

    # Look for .env.template in plugin build directory
    template_file = plugin_build_dir / ".env.template"
    if not template_file.exists():
        if verbose:
            print(f"No .env.template found in {plugin_name}")
        return

    # Target file path
    target_file = env_dir / f".env.{plugin_name}"

    # Only copy if target doesn't exist (don't overwrite user edits)
    if target_file.exists():
        if verbose:
            print(f"⚠ {target_file} already exists, skipping")
        return

    # Copy template
    shutil.copy2(template_file, target_file)
    if verbose:
        print(f"✓ Copied .env.template -> {target_file}")


def handle_registry_operations(component, component_name: str, image_tag: str, container_runtime: str, verbose: bool = False) -> str:
    """Handle registry tagging and pushing for a built component.

    This function is shared between Dagger and plain Python implementations.
    It tags the locally built image with the registry path and optionally pushes it.

    Args:
        component: BuildableConfig component (GatewayConfig or PluginConfig)
        component_name: Name of the component (gateway or plugin name)
        image_tag: Current local image tag
        container_runtime: Container runtime to use ("docker" or "podman")
        verbose: Print verbose output

    Returns:
        Final image tag (registry path if registry enabled, otherwise original tag)

    Raises:
        TypeError: If component is not a BuildableConfig instance
        ValueError: If registry enabled but missing required configuration
        subprocess.CalledProcessError: If tag or push command fails

    Examples:
        >>> from mcpgateway.tools.builder.schema import GatewayConfig, RegistryConfig
        >>> # Test with registry disabled (returns original tag)
        >>> gateway = GatewayConfig(image="test:latest")
        >>> result = handle_registry_operations(gateway, "gateway", "test:latest", "docker")
        >>> result
        'test:latest'

        >>> # Test type checking - wrong type raises TypeError
        >>> try:
        ...     handle_registry_operations("not a config", "test", "tag:latest", "docker")
        ... except TypeError as e:
        ...     "BuildableConfig" in str(e)
        True

        >>> # Test validation error - registry enabled but missing config
        >>> from mcpgateway.tools.builder.schema import GatewayConfig, RegistryConfig
        >>> gateway_bad = GatewayConfig(
        ...     image="test:latest",
        ...     registry=RegistryConfig(enabled=True, url="docker.io")  # missing namespace
        ... )
        >>> try:
        ...     handle_registry_operations(gateway_bad, "gateway", "test:latest", "docker")
        ... except ValueError as e:
        ...     "missing" in str(e) and "namespace" in str(e)
        True

        >>> # Test validation error - missing URL
        >>> gateway_bad2 = GatewayConfig(
        ...     image="test:latest",
        ...     registry=RegistryConfig(enabled=True, namespace="myns")  # missing url
        ... )
        >>> try:
        ...     handle_registry_operations(gateway_bad2, "gateway", "test:latest", "docker")
        ... except ValueError as e:
        ...     "missing" in str(e) and "url" in str(e)
        True

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(handle_registry_operations)
        >>> list(sig.parameters.keys())
        ['component', 'component_name', 'image_tag', 'container_runtime', 'verbose']

        >>> # Test return type
        >>> sig.return_annotation
        <class 'str'>
    """
    # First-Party
    from mcpgateway.tools.builder.schema import BuildableConfig

    # Type check for better error messages
    if not isinstance(component, BuildableConfig):
        raise TypeError(f"Component must be a BuildableConfig instance, got {type(component)}")

    # Check if registry is enabled
    if not component.registry or not component.registry.enabled:
        return image_tag

    registry_config = component.registry

    # Validate registry configuration
    if not registry_config.url or not registry_config.namespace:
        raise ValueError(f"Registry enabled for {component_name} but missing 'url' or 'namespace' configuration")

    # Construct registry image path
    # Format: {registry_url}/{namespace}/{image_name}:{tag}
    base_image_name = image_tag.split(":")[0].split("/")[-1]  # Extract base name (e.g., "mcpgateway-gateway")
    image_version = image_tag.split(":")[-1] if ":" in image_tag else "latest"  # Extract tag
    registry_image = f"{registry_config.url}/{registry_config.namespace}/{base_image_name}:{image_version}"

    # Tag image for registry
    if verbose:
        console.print(f"[dim]Tagging {image_tag} as {registry_image}[/dim]")
    tag_cmd = [container_runtime, "tag", image_tag, registry_image]
    result = subprocess.run(tag_cmd, capture_output=True, text=True, check=True)  # nosec B603, B607
    if result.stdout and verbose:
        console.print(result.stdout)

    # Push to registry if enabled
    if registry_config.push:
        if verbose:
            console.print(f"[blue]Pushing {registry_image} to registry...[/blue]")

        # Build push command with TLS options
        push_cmd = [container_runtime, "push"]

        # For podman, add --tls-verify=false for registries with self-signed certs
        # This is common for OpenShift internal registries and local development
        if container_runtime == "podman":
            push_cmd.append("--tls-verify=false")

        push_cmd.append(registry_image)

        try:
            result = subprocess.run(push_cmd, capture_output=True, text=True, check=True)  # nosec B603, B607
            if result.stdout and verbose:
                console.print(result.stdout)
            console.print(f"[green]✓ Pushed to registry: {registry_image}[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]✗ Failed to push to registry: {e}[/red]")
            if e.stderr:
                console.print(f"[red]Error output: {e.stderr}[/red]")
            console.print("[yellow]Tip: Authenticate to the registry first:[/yellow]")
            console.print(f"  {container_runtime} login {registry_config.url}")
            raise

    # Update component image reference to use registry path for manifests
    component.image = registry_image

    return registry_image


# Docker Compose Utilities


def get_docker_compose_command() -> List[str]:
    """Detect and return available docker compose command.

    Tries to detect docker compose plugin first, then falls back to
    standalone docker-compose command.

    Returns:
        Command to use: ["docker", "compose"] or ["docker-compose"]

    Raises:
        RuntimeError: If neither command is available

    Examples:
        >>> # Test that function returns a list
        >>> try:
        ...     cmd = get_docker_compose_command()
        ...     isinstance(cmd, list)
        ... except RuntimeError:
        ...     # Docker compose not installed in test environment
        ...     True
        True

        >>> # Test that it returns valid command formats
        >>> try:
        ...     cmd = get_docker_compose_command()
        ...     # Should be either ["docker", "compose"] or ["docker-compose"]
        ...     cmd in [["docker", "compose"], ["docker-compose"]]
        ... except RuntimeError:
        ...     # Docker compose not installed
        ...     True
        True

        >>> # Test error case (requires mocking, shown for documentation)
        >>> # from unittest.mock import patch
        >>> # with patch('shutil.which', return_value=None):
        >>> #     try:
        >>> #         get_docker_compose_command()
        >>> #     except RuntimeError as e:
        >>> #         "Docker Compose not found" in str(e)
        >>> #     True
    """
    # Try docker compose (new plugin) first
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)  # nosec B603, B607
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Fall back to standalone docker-compose
    if shutil.which("docker-compose"):
        return ["docker-compose"]

    raise RuntimeError("Docker Compose not found. Install docker compose plugin or docker-compose.")


def run_compose(compose_file: Path, args: List[str], verbose: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run docker compose command with given arguments.

    Args:
        compose_file: Path to docker-compose.yaml
        args: Arguments to pass to compose (e.g., ["up", "-d"])
        verbose: Print verbose output
        check: Raise exception on non-zero exit code

    Returns:
        CompletedProcess instance

    Raises:
        FileNotFoundError: If compose_file doesn't exist
        RuntimeError: If docker compose command fails (when check=True)

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> # Test with non-existent file
        >>> try:
        ...     run_compose(Path("/nonexistent/docker-compose.yaml"), ["ps"])
        ... except FileNotFoundError as e:
        ...     "Compose file not found" in str(e)
        True

        >>> # Test that args are properly formatted
        >>> args = ["up", "-d"]
        >>> isinstance(args, list)
        True
        >>> all(isinstance(arg, str) for arg in args)
        True

        >>> # Real execution would require docker compose installed:
        >>> # with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
        >>> #     result = run_compose(Path(f.name), ["--version"], check=False)
        >>> #     isinstance(result, subprocess.CompletedProcess)
    """
    if not compose_file.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_file}")

    compose_cmd = get_docker_compose_command()
    full_cmd = compose_cmd + ["-f", str(compose_file)] + args

    if verbose:
        console.print(f"[dim]Running: {' '.join(full_cmd)}[/dim]")

    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, check=check)  # nosec B603, B607
        return result
    except subprocess.CalledProcessError as e:
        console.print("\n[red bold]Docker Compose command failed:[/red bold]")
        if e.stdout:
            console.print(f"[yellow]Output:[/yellow]\n{e.stdout}")
        if e.stderr:
            console.print(f"[red]Error:[/red]\n{e.stderr}")
        raise RuntimeError(f"Docker Compose failed with exit code {e.returncode}") from e


def deploy_compose(compose_file: Path, verbose: bool = False) -> None:
    """Deploy using docker compose up -d.

    Args:
        compose_file: Path to docker-compose.yaml
        verbose: Print verbose output

    Raises:
        RuntimeError: If deployment fails

    Examples:
        >>> from pathlib import Path
        >>> # Test that function signature is correct
        >>> import inspect
        >>> sig = inspect.signature(deploy_compose)
        >>> 'compose_file' in sig.parameters
        True
        >>> 'verbose' in sig.parameters
        True

        >>> # Test with non-existent file (would fail at run_compose)
        >>> # deploy_compose(Path("/nonexistent.yaml"))  # Raises FileNotFoundError
    """
    result = run_compose(compose_file, ["up", "-d"], verbose=verbose)
    if result.stdout and verbose:
        console.print(result.stdout)
    console.print("[green]✓ Deployed with Docker Compose[/green]")


def verify_compose(compose_file: Path, verbose: bool = False) -> str:
    """Verify Docker Compose deployment with ps command.

    Args:
        compose_file: Path to docker-compose.yaml
        verbose: Print verbose output

    Returns:
        Output from docker compose ps command

    Examples:
        >>> from pathlib import Path
        >>> # Test return type
        >>> import inspect
        >>> sig = inspect.signature(verify_compose)
        >>> sig.return_annotation
        <class 'str'>

        >>> # Test parameters
        >>> list(sig.parameters.keys())
        ['compose_file', 'verbose']

        >>> # Actual execution requires docker compose:
        >>> # output = verify_compose(Path("docker-compose.yaml"))
        >>> # isinstance(output, str)
    """
    result = run_compose(compose_file, ["ps"], verbose=verbose, check=False)
    return result.stdout


def destroy_compose(compose_file: Path, verbose: bool = False) -> None:
    """Destroy Docker Compose deployment with down -v.

    Args:
        compose_file: Path to docker-compose.yaml
        verbose: Print verbose output

    Raises:
        RuntimeError: If destruction fails

    Examples:
        >>> from pathlib import Path
        >>> # Test with non-existent file (graceful handling)
        >>> destroy_compose(Path("/nonexistent/docker-compose.yaml"), verbose=False)
        Compose file not found: /nonexistent/docker-compose.yaml
        Nothing to destroy

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(destroy_compose)
        >>> 'verbose' in sig.parameters
        True
    """
    if not compose_file.exists():
        console.print(f"[yellow]Compose file not found: {compose_file}[/yellow]")
        console.print("[yellow]Nothing to destroy[/yellow]")
        return

    result = run_compose(compose_file, ["down", "-v"], verbose=verbose)
    if result.stdout and verbose:
        console.print(result.stdout)
    console.print("[green]✓ Destroyed Docker Compose deployment[/green]")


# Kubernetes kubectl utilities


def deploy_kubernetes(manifests_dir: Path, verbose: bool = False) -> None:
    """Deploy to Kubernetes using kubectl.

    Applies manifests in correct order:
    1. Deployments (creates namespaces)
    2. Certificate resources (secrets or cert-manager CRDs)
    3. ConfigMaps (plugins configuration)
    4. Infrastructure (PostgreSQL, Redis)
    5. OpenShift Routes (if configured)

    Excludes plugins-config.yaml (not a Kubernetes resource).

    Args:
        manifests_dir: Path to directory containing Kubernetes manifests
        verbose: Print verbose output

    Raises:
        RuntimeError: If kubectl not found or deployment fails

    Examples:
        >>> from pathlib import Path
        >>> import shutil
        >>> # Test that function checks for kubectl
        >>> if not shutil.which("kubectl"):
        ...     # Would raise RuntimeError
        ...     print("kubectl not found")
        ... else:
        ...     print("kubectl available")
        kubectl...

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(deploy_kubernetes)
        >>> list(sig.parameters.keys())
        ['manifests_dir', 'verbose']
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found. Cannot deploy to Kubernetes.")

    # Get all manifest files, excluding plugins-config.yaml (not a Kubernetes resource)
    all_manifests = sorted(manifests_dir.glob("*.yaml"))
    all_manifests = [m for m in all_manifests if m.name != "plugins-config.yaml"]

    # Identify different types of manifests
    cert_secrets = manifests_dir / "cert-secrets.yaml"
    cert_manager_certs = manifests_dir / "cert-manager-certificates.yaml"
    postgres_deploy = manifests_dir / "postgres-deployment.yaml"
    redis_deploy = manifests_dir / "redis-deployment.yaml"
    plugins_configmap = manifests_dir / "plugins-configmap.yaml"

    # 1. Apply all deployments first (creates namespaces)
    deployment_files = [m for m in all_manifests if m.name.endswith("-deployment.yaml") and m not in [cert_secrets, postgres_deploy, redis_deploy]]

    # Apply deployment files (this creates the namespace)
    for manifest in deployment_files:
        result = subprocess.run(["kubectl", "apply", "-f", str(manifest)], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 2. Apply certificate resources (now namespace exists)
    # Check for both cert-secrets.yaml (local mode) and cert-manager-certificates.yaml (cert-manager mode)
    if cert_manager_certs.exists():
        result = subprocess.run(["kubectl", "apply", "-f", str(cert_manager_certs)], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")
    elif cert_secrets.exists():
        result = subprocess.run(["kubectl", "apply", "-f", str(cert_secrets)], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 3. Apply ConfigMaps (needed by deployments)
    if plugins_configmap.exists():
        result = subprocess.run(["kubectl", "apply", "-f", str(plugins_configmap)], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 4. Apply infrastructure
    for infra_file in [postgres_deploy, redis_deploy]:
        if infra_file.exists():
            result = subprocess.run(["kubectl", "apply", "-f", str(infra_file)], capture_output=True, text=True, check=False)  # nosec B603, B607
            if result.stdout and verbose:
                console.print(result.stdout)
            if result.returncode != 0:
                raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 5. Apply OpenShift Routes (if configured)
    gateway_route = manifests_dir / "gateway-route.yaml"
    if gateway_route.exists():
        result = subprocess.run(["kubectl", "apply", "-f", str(gateway_route)], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            # Don't fail on Route errors (may not be on OpenShift)
            if verbose:
                console.print(f"[yellow]Warning: Could not apply Route (may not be on OpenShift): {result.stderr}[/yellow]")

    console.print("[green]✓ Deployed to Kubernetes[/green]")


def verify_kubernetes(namespace: str, wait: bool = False, timeout: int = 300, verbose: bool = False) -> str:
    """Verify Kubernetes deployment health.

    Args:
        namespace: Kubernetes namespace to check
        wait: Wait for pods to be ready
        timeout: Wait timeout in seconds
        verbose: Print verbose output

    Returns:
        String output from kubectl get pods

    Raises:
        RuntimeError: If kubectl not found or verification fails

    Examples:
        >>> # Test function signature and return type
        >>> import inspect
        >>> sig = inspect.signature(verify_kubernetes)
        >>> sig.return_annotation
        <class 'str'>

        >>> # Test parameters
        >>> params = list(sig.parameters.keys())
        >>> 'namespace' in params and 'wait' in params and 'timeout' in params
        True

        >>> # Test default timeout value
        >>> sig.parameters['timeout'].default
        300
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found. Cannot verify Kubernetes deployment.")

    # Get pod status
    result = subprocess.run(["kubectl", "get", "pods", "-n", namespace], capture_output=True, text=True, check=False)  # nosec B603, B607
    output = result.stdout if result.stdout else ""
    if result.returncode != 0:
        raise RuntimeError(f"kubectl get pods failed: {result.stderr}")

    # Wait for pods if requested
    if wait:
        result = subprocess.run(["kubectl", "wait", "--for=condition=Ready", "pod", "--all", "-n", namespace, f"--timeout={timeout}s"], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl wait failed: {result.stderr}")

    return output


def destroy_kubernetes(manifests_dir: Path, verbose: bool = False) -> None:
    """Destroy Kubernetes deployment.

    Args:
        manifests_dir: Path to directory containing Kubernetes manifests
        verbose: Print verbose output

    Raises:
        RuntimeError: If kubectl not found or destruction fails

    Examples:
        >>> from pathlib import Path
        >>> # Test with non-existent directory (graceful handling)
        >>> import shutil
        >>> if shutil.which("kubectl"):
        ...     destroy_kubernetes(Path("/nonexistent/manifests"), verbose=False)
        ... else:
        ...     print("kubectl not available")
        Manifests directory not found: /nonexistent/manifests
        Nothing to destroy

        >>> # Test function signature
        >>> import inspect
        >>> sig = inspect.signature(destroy_kubernetes)
        >>> list(sig.parameters.keys())
        ['manifests_dir', 'verbose']
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found. Cannot destroy Kubernetes deployment.")

    if not manifests_dir.exists():
        console.print(f"[yellow]Manifests directory not found: {manifests_dir}[/yellow]")
        console.print("[yellow]Nothing to destroy[/yellow]")
        return

    # Delete all manifests except plugins-config.yaml
    all_manifests = sorted(manifests_dir.glob("*.yaml"))
    all_manifests = [m for m in all_manifests if m.name != "plugins-config.yaml"]

    for manifest in all_manifests:
        result = subprocess.run(["kubectl", "delete", "-f", str(manifest), "--ignore-not-found=true"], capture_output=True, text=True, check=False)  # nosec B603, B607
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0 and "NotFound" not in result.stderr:
            console.print(f"[yellow]Warning: {result.stderr}[/yellow]")

    console.print("[green]✓ Destroyed Kubernetes deployment[/green]")
