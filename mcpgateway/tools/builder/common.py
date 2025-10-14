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
import subprocess
from typing import Any, Dict, List

# Third-Party
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
import yaml

console = Console()


def get_deploy_dir() -> Path:
    """Get deployment directory from environment variable or default.

    Checks MCP_DEPLOY_DIR environment variable, defaults to './deploy'.

    Returns:
        Path to deployment directory
    """
    deploy_dir = os.environ.get("MCP_DEPLOY_DIR", "./deploy")
    return Path(deploy_dir)


def load_config(config_file: str) -> Dict[str, Any]:
    """Load and parse YAML configuration file.

    Args:
        config_file: Path to mcp-stack.yaml configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        FileNotFoundError: If configuration file doesn't exist
    """
    config_path = Path(config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_plugin_config(config: Dict[str, Any], output_dir: Path, verbose: bool = False) -> Path:
    """Generate plugin config.yaml for gateway from mcp-stack.yaml.

    This function is shared between Dagger and plain Python implementations
    to avoid code duplication.

    Args:
        config: Parsed mcp-stack.yaml configuration
        output_dir: Output directory for generated config
        verbose: Print verbose output

    Returns:
        Path to generated plugins-config.yaml file

    Raises:
        FileNotFoundError: If template directory not found
    """

    deployment_type = config["deployment"]["type"]
    plugins = config.get("plugins", [])

    # Load template
    template_dir = Path(__file__).parent / "templates"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("plugins-config.yaml.j2")

    # Prepare plugin data with computed URLs
    plugin_data = []
    for plugin in plugins:
        plugin_name = plugin["name"]
        port = plugin.get("port", 8000)

        # Determine URL based on deployment type
        if deployment_type == "compose":
            # Use container hostname (lowercase)
            hostname = plugin_name.lower()
            # Use HTTPS if mTLS is enabled
            protocol = "https" if plugin.get("mtls_enabled", True) else "http"
            url = f"{protocol}://{hostname}:{port}/mcp"
        else:  # kubernetes
            # Use Kubernetes service DNS
            namespace = config["deployment"].get("namespace", "mcp-gateway")
            service_name = f"mcp-plugin-{plugin_name.lower()}"
            protocol = "https" if plugin.get("mtls_enabled", True) else "http"
            url = f"{protocol}://{service_name}.{namespace}.svc:{port}/mcp"

        # Build plugin entry with computed URL
        plugin_entry = {
            "name": plugin_name,
            "port": port,
            "url": url,
        }

        # Merge plugin_overrides (client-side config only, excludes 'config')
        # Allowed client-side fields that plugin manager uses
        if "plugin_overrides" in plugin:
            overrides = plugin["plugin_overrides"]
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


def generate_kubernetes_manifests(config: Dict[str, Any], output_dir: Path, verbose: bool = False) -> None:
    """Generate Kubernetes manifests from configuration.

    Args:
        config: Parsed mcp-stack.yaml configuration
        output_dir: Output directory for manifests
        verbose: Print verbose output

    Raises:
        FileNotFoundError: If template directory not found
    """

    # Load templates
    template_dir = Path(__file__).parent / "templates" / "kubernetes"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Auto-detect and assign env files if not specified
    _auto_detect_env_files(config, output_dir, verbose=verbose)

    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Generate namespace
    namespace = config["deployment"].get("namespace", "mcp-gateway")

    # Generate mTLS certificate secrets if enabled
    gateway_mtls = config.get("gateway", {}).get("mtls_enabled", True)
    if gateway_mtls:

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
        for plugin in config.get("plugins", []):
            if plugin.get("mtls_enabled", True):
                plugin_name = plugin["name"]
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
    infrastructure = config.get("infrastructure", {})

    # PostgreSQL
    postgres_config = infrastructure.get("postgres", {})
    if postgres_config.get("enabled", True):
        postgres_template = env.get_template("postgres.yaml.j2")
        postgres_manifest = postgres_template.render(
            namespace=namespace,
            image=postgres_config.get("image", "postgres:17"),
            database=postgres_config.get("database", "mcp"),
            user=postgres_config.get("user", "postgres"),
            password=postgres_config.get("password", "mysecretpassword"),
            storage_size=postgres_config.get("storage_size", "10Gi"),
            storage_class=postgres_config.get("storage_class"),
        )
        (output_dir / "postgres-deployment.yaml").write_text(postgres_manifest)
        if verbose:
            print("  ✓ PostgreSQL deployment manifest generated")

    # Redis
    redis_config = infrastructure.get("redis", {})
    if redis_config.get("enabled", True):
        redis_template = env.get_template("redis.yaml.j2")
        redis_manifest = redis_template.render(namespace=namespace, image=redis_config.get("image", "redis:latest"))
        (output_dir / "redis-deployment.yaml").write_text(redis_manifest)
        if verbose:
            print("  ✓ Redis deployment manifest generated")

    # Generate gateway deployment
    gateway_template = env.get_template("deployment.yaml.j2")
    gateway_config = config["gateway"].copy()
    gateway_config["name"] = "mcpgateway"
    gateway_config["namespace"] = namespace

    # Add DATABASE_URL and REDIS_URL to gateway environment if infrastructure is enabled
    if "env_vars" not in gateway_config:
        gateway_config["env_vars"] = {}

    # Add init containers to wait for infrastructure services
    init_containers = []

    if postgres_config.get("enabled", True):
        db_user = postgres_config.get("user", "postgres")
        db_password = postgres_config.get("password", "mysecretpassword")
        db_name = postgres_config.get("database", "mcp")
        gateway_config["env_vars"]["DATABASE_URL"] = f"postgresql://{db_user}:{db_password}@postgres:5432/{db_name}"

        # Add init container to wait for PostgreSQL
        init_containers.append({"name": "wait-for-postgres", "image": "busybox:1.36", "command": ["sh", "-c", "until nc -z postgres 5432; do echo waiting for postgres; sleep 2; done"]})

    if redis_config.get("enabled", True):
        gateway_config["env_vars"]["REDIS_URL"] = "redis://redis:6379/0"

        # Add init container to wait for Redis
        init_containers.append({"name": "wait-for-redis", "image": "busybox:1.36", "command": ["sh", "-c", "until nc -z redis 6379; do echo waiting for redis; sleep 2; done"]})

    if init_containers:
        gateway_config["init_containers"] = init_containers

    gateway_manifest = gateway_template.render(**gateway_config)
    (output_dir / "gateway-deployment.yaml").write_text(gateway_manifest)

    # Generate plugin deployments
    for plugin in config.get("plugins", []):
        plugin_config = plugin.copy()
        plugin_config["name"] = f"mcp-plugin-{plugin['name'].lower()}"
        plugin_config["namespace"] = namespace
        plugin_manifest = gateway_template.render(**plugin_config)
        (output_dir / f"plugin-{plugin['name'].lower()}-deployment.yaml").write_text(plugin_manifest)

    if verbose:
        print(f"✓ Kubernetes manifests generated in {output_dir}")


def generate_compose_manifests(config: Dict[str, Any], output_dir: Path, verbose: bool = False) -> None:
    """Generate Docker Compose manifest from configuration.

    Args:
        config: Parsed mcp-stack.yaml configuration
        output_dir: Output directory for manifests
        verbose: Print verbose output

    Raises:
        FileNotFoundError: If template directory not found
    """

    # Load templates
    template_dir = Path(__file__).parent / "templates" / "compose"
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Auto-detect and assign env files if not specified
    _auto_detect_env_files(config, output_dir, verbose=verbose)

    # Auto-assign host_ports if expose_port is true but host_port not specified
    plugins = config.get("plugins", [])
    next_host_port = 8000
    for plugin in plugins:
        # Set default port if not specified
        if "port" not in plugin:
            plugin["port"] = 8000

        # Auto-assign host_port if expose_port is true
        if plugin.get("expose_port", False) and "host_port" not in plugin:
            plugin["host_port"] = next_host_port
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

    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Generate compose file
    compose_template = env.get_template("docker-compose.yaml.j2")
    compose_manifest = compose_template.render(**config, cert_paths=cert_paths)
    (output_dir / "docker-compose.yaml").write_text(compose_manifest)

    if verbose:
        print(f"✓ Compose manifest generated in {output_dir}")


def _auto_detect_env_files(config: Dict[str, Any], output_dir: Path, verbose: bool = False) -> None:
    """Auto-detect and assign env files if not explicitly specified.

    If env_file is not specified in the config, check if {deploy_dir}/env/.env.{name}
    exists and use it. Warn the user when auto-detection is used.

    Args:
        config: Parsed mcp-stack.yaml configuration (modified in-place)
        output_dir: Output directory where manifests will be generated (for relative paths)
        verbose: Print verbose output
    """
    deploy_dir = get_deploy_dir()
    env_dir = deploy_dir / "env"

    # Check gateway
    gateway = config.get("gateway", {})
    if "env_file" not in gateway or not gateway["env_file"]:
        gateway_env = env_dir / ".env.gateway"
        if gateway_env.exists():
            # Make path relative to output_dir (where docker-compose.yaml will be)
            relative_path = os.path.relpath(gateway_env, output_dir)
            gateway["env_file"] = relative_path
            print(f"⚠ Auto-detected env file: {gateway_env}")
            if verbose:
                print("   (Gateway env_file not specified in config)")

    # Check plugins
    plugins = config.get("plugins", [])
    for plugin in plugins:
        plugin_name = plugin["name"]
        if "env_file" not in plugin or not plugin["env_file"]:
            plugin_env = env_dir / f".env.{plugin_name}"
            if plugin_env.exists():
                # Make path relative to output_dir (where docker-compose.yaml will be)
                relative_path = os.path.relpath(plugin_env, output_dir)
                plugin["env_file"] = relative_path
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


# Docker Compose Utilities


def get_docker_compose_command() -> List[str]:
    """Detect and return available docker compose command.

    Tries to detect docker compose plugin first, then falls back to
    standalone docker-compose command.

    Returns:
        Command to use: ["docker", "compose"] or ["docker-compose"]

    Raises:
        RuntimeError: If neither command is available
    """
    # Try docker compose (new plugin) first
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
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
    """
    if not compose_file.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_file}")

    compose_cmd = get_docker_compose_command()
    full_cmd = compose_cmd + ["-f", str(compose_file)] + args

    if verbose:
        console.print(f"[dim]Running: {' '.join(full_cmd)}[/dim]")

    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, check=check)
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
    2. Certificate secrets
    3. Infrastructure (PostgreSQL, Redis)

    Excludes plugins-config.yaml (not a Kubernetes resource).

    Args:
        manifests_dir: Path to directory containing Kubernetes manifests
        verbose: Print verbose output

    Raises:
        RuntimeError: If kubectl not found or deployment fails
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found. Cannot deploy to Kubernetes.")

    # Get all manifest files, excluding plugins-config.yaml
    all_manifests = sorted(manifests_dir.glob("*.yaml"))
    all_manifests = [m for m in all_manifests if m.name != "plugins-config.yaml"]

    # Apply in order to handle dependencies
    cert_secrets = manifests_dir / "cert-secrets.yaml"
    postgres_deploy = manifests_dir / "postgres-deployment.yaml"
    redis_deploy = manifests_dir / "redis-deployment.yaml"

    # 1. Apply all deployments first (creates namespaces)
    deployment_files = [m for m in all_manifests if m.name.endswith("-deployment.yaml") and m != cert_secrets and m != postgres_deploy and m != redis_deploy]

    # Apply deployment files
    for manifest in deployment_files:
        result = subprocess.run(["kubectl", "apply", "-f", str(manifest)], capture_output=True, text=True, check=False)
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 2. Apply certificate secrets (now namespace exists)
    if cert_secrets.exists():
        result = subprocess.run(["kubectl", "apply", "-f", str(cert_secrets)], capture_output=True, text=True, check=False)
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl apply failed: {result.stderr}")

    # 3. Apply infrastructure
    for infra_file in [postgres_deploy, redis_deploy]:
        if infra_file.exists():
            result = subprocess.run(["kubectl", "apply", "-f", str(infra_file)], capture_output=True, text=True, check=False)
            if result.stdout and verbose:
                console.print(result.stdout)
            if result.returncode != 0:
                raise RuntimeError(f"kubectl apply failed: {result.stderr}")

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
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found. Cannot verify Kubernetes deployment.")

    # Get pod status
    result = subprocess.run(["kubectl", "get", "pods", "-n", namespace], capture_output=True, text=True, check=False)
    output = result.stdout if result.stdout else ""
    if result.returncode != 0:
        raise RuntimeError(f"kubectl get pods failed: {result.stderr}")

    # Wait for pods if requested
    if wait:
        result = subprocess.run(["kubectl", "wait", "--for=condition=Ready", "pod", "--all", "-n", namespace, f"--timeout={timeout}s"], capture_output=True, text=True, check=False)
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
        result = subprocess.run(["kubectl", "delete", "-f", str(manifest), "--ignore-not-found=true"], capture_output=True, text=True, check=False)
        if result.stdout and verbose:
            console.print(result.stdout)
        if result.returncode != 0 and "NotFound" not in result.stderr:
            console.print(f"[yellow]Warning: {result.stderr}[/yellow]")

    console.print("[green]✓ Destroyed Kubernetes deployment[/green]")
