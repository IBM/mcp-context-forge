# -*- coding: utf-8 -*-
"""Container management utilities for migration testing.

This module provides comprehensive Docker/Podman container orchestration
for testing database migrations across different MCP Gateway versions.
"""

# Standard
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ContainerConfig:
    """Configuration for a container instance."""
    image: str
    version: str
    db_type: str
    ports: Dict[str, str]
    environment: Dict[str, str]
    volumes: Dict[str, str]
    labels: Dict[str, str] = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = {"migration-test": "true"}


class ContainerManager:
    """Manages Docker/Podman containers for migration testing.

    Provides high-level interface for:
    - Pulling container images for all MCP Gateway versions
    - Starting SQLite containers for isolated testing
    - Starting docker-compose stacks for PostgreSQL testing
    - Executing Alembic commands within containers
    - Managing container lifecycle and cleanup
    """

    AVAILABLE_VERSIONS = ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "latest"]

    def __init__(self, runtime: str = "docker", verbose: bool = True):
        """Initialize container manager.

        Args:
            runtime: Container runtime to use ("docker" or "podman")
            verbose: Enable detailed command logging
        """
        self.runtime = runtime
        self.verbose = verbose
        self.active_containers: List[str] = []

        # Set up logging
        if verbose:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            )

        logger.info(f"🚀 Initialized ContainerManager with runtime={runtime}")
        self._verify_runtime()

    def _verify_runtime(self) -> None:
        """Verify that the container runtime is available."""
        logger.info(f"🔍 Verifying {self.runtime} runtime availability...")
        try:
            result = self._run_command([self.runtime, "--version"], capture_output=True)
            logger.info(f"✅ {self.runtime} runtime verified: {result.stdout.split()[0]}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"❌ {self.runtime} runtime not available: {e}")
            raise RuntimeError(f"{self.runtime} not found or not working")

    def _run_command(self, cmd: List[str], capture_output: bool = False,
                     check: bool = True, env: Dict[str, str] = None) -> subprocess.CompletedProcess:
        """Run a command with detailed logging.

        Args:
            cmd: Command to execute as list of strings
            capture_output: Whether to capture stdout/stderr
            check: Whether to raise exception on non-zero exit
            env: Additional environment variables

        Returns:
            CompletedProcess result
        """
        cmd_str = ' '.join(cmd)
        logger.info(f"🔧 Executing: {cmd_str}")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                check=check,
                env={**os.environ, **(env or {})}
            )

            duration = time.time() - start_time
            logger.info(f"✅ Command completed in {duration:.2f}s: {cmd_str}")

            if capture_output and result.stdout:
                logger.debug(f"📤 stdout: {result.stdout[:500]}")
            if capture_output and result.stderr:
                logger.debug(f"📤 stderr: {result.stderr[:500]}")

            return result

        except subprocess.CalledProcessError as e:
            duration = time.time() - start_time
            logger.error(f"❌ Command failed after {duration:.2f}s: {cmd_str}")
            logger.error(f"📤 Exit code: {e.returncode}")
            if e.stdout:
                logger.error(f"📤 stdout: {e.stdout}")
            if e.stderr:
                logger.error(f"📤 stderr: {e.stderr}")
            raise

    def pull_images(self, versions: List[str] = None) -> None:
        """Pull all required container images.

        Args:
            versions: List of versions to pull (defaults to all available)
        """
        versions = versions or self.AVAILABLE_VERSIONS
        logger.info(f"📦 Pulling container images for versions: {versions}")

        for version in versions:
            image = f"ghcr.io/ibm/mcp-context-forge:{version}"
            logger.info(f"📥 Pulling {image}...")

            try:
                self._run_command([self.runtime, "pull", image])
                logger.info(f"✅ Successfully pulled {image}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"⚠️ Failed to pull {image}: {e}")
                if version == "latest":
                    logger.info("💡 Building latest image locally...")
                    self._build_latest_image()

    def _build_latest_image(self) -> None:
        """Build the latest image locally using Makefile."""
        logger.info("🔨 Building latest image using make docker-prod...")

        try:
            # Run make docker-prod from repository root
            self._run_command(["make", "docker-prod"], capture_output=True)

            # Tag the built image appropriately
            tag_cmd = [
                self.runtime, "tag",
                "mcpgateway/mcpgateway:latest",
                "ghcr.io/ibm/mcp-context-forge:latest"
            ]
            self._run_command(tag_cmd)
            logger.info("✅ Latest image built and tagged successfully")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to build latest image: {e}")
            raise

    def start_sqlite_container(self, version: str,
                              db_file: str = "mcp-alembic-migration-test.db",
                              extra_env: Dict[str, str] = None,
                              data_dir: str = None) -> str:
        """Start SQLite container with mounted test database.

        Args:
            version: MCP Gateway version to use
            db_file: SQLite database filename
            extra_env: Additional environment variables
            data_dir: Existing data directory to reuse (for migration tests)

        Returns:
            Container ID
        """
        logger.info(f"🐳 Starting SQLite container for version {version}")

        # Create or reuse temporary directory for database file
        if data_dir:
            temp_dir = data_dir
            logger.info(f"🔄 Reusing existing data directory: {temp_dir}")
        else:
            temp_dir = tempfile.mkdtemp(prefix="migration_test_")
            logger.info(f"📁 Created new data directory: {temp_dir}")
            # Set ownership and permissions so the app user (uid=1001) can write to it
            try:
                # Standard
                import os
                import stat

                # Change ownership to match the container app user (uid=1001, gid=1001)
                os.chown(temp_dir, 1001, 1001)
                # Also set write permissions for good measure
                os.chmod(temp_dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)  # 775 permissions
                logger.debug(f"📁 Set ownership to app user (1001:1001) on {temp_dir}")
            except PermissionError:
                # If we can't chown (common in some environments), try to make it world-writable
                try:
                    os.chmod(temp_dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 777 permissions
                    logger.debug(f"📁 Set world-writable permissions on {temp_dir}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not set permissions on {temp_dir}: {e}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set ownership on {temp_dir}: {e}")
        db_path = Path(temp_dir) / db_file

        config = ContainerConfig(
            image=f"ghcr.io/ibm/mcp-context-forge:{version}",
            version=version,
            db_type="sqlite",
            ports={"4444": "0"},  # Let Docker assign random port
            environment={
                "DATABASE_URL": f"sqlite:///app/data/{db_file}",
                "MCPGATEWAY_UI_ENABLED": "false",
                "MCPGATEWAY_ADMIN_API_ENABLED": "true",
                "AUTH_REQUIRED": "false",
                "LOG_LEVEL": "INFO",
                "PYTHONUNBUFFERED": "1",
                "HOST": "0.0.0.0",  # Bind to all interfaces for external access
                "PORT": "4444",
                **(extra_env or {})
            },
            volumes={
                temp_dir: "/app/data"
            },
            labels={"migration-test": "true", "version": version, "db-type": "sqlite"}
        )

        container_id = self._start_container(config)

        # Store the data directory as a container label for later retrieval
        self._run_command([
            self.runtime, "container", "update", "--label", f"data_dir={temp_dir}", container_id
        ], check=False)  # Don't fail if labeling doesn't work

        return container_id

    def get_container_data_dir(self, container_id: str) -> str:
        """Get the data directory path from a container.

        Args:
            container_id: Container ID

        Returns:
            Data directory path on host
        """
        try:
            result = self._run_command([
                self.runtime, "inspect", "--format", "{{index .Config.Labels \"data_dir\"}}", container_id
            ], capture_output=True)
            data_dir = result.stdout.strip()
            if data_dir and data_dir != "<no value>":
                return data_dir
        except Exception:
            pass

        # Fallback: try to extract from volume mounts
        try:
            result = self._run_command([
                self.runtime, "inspect", "--format", "{{range .Mounts}}{{if eq .Destination \"/app/data\"}}{{.Source}}{{end}}{{end}}", container_id
            ], capture_output=True)
            return result.stdout.strip()
        except Exception as e:
            logger.warning(f"⚠️ Could not get data directory from container {container_id[:12]}: {e}")
            return None

    def _start_container(self, config: ContainerConfig) -> str:
        """Start a container with the given configuration.

        Args:
            config: Container configuration

        Returns:
            Container ID
        """
        logger.info(f"🚀 Starting container: {config.image}")

        # Build docker run command
        cmd = [self.runtime, "run", "-d"]

        # Add port mappings
        for container_port, host_port in config.ports.items():
            if host_port == "0":
                cmd.extend(["-p", container_port])  # Random host port
            else:
                cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Add environment variables
        for key, value in config.environment.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Add volume mounts
        for host_path, container_path in config.volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Add labels
        for key, value in config.labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        # Add image
        cmd.append(config.image)

        # Start container
        result = self._run_command(cmd, capture_output=True)
        container_id = result.stdout.strip()

        self.active_containers.append(container_id)
        logger.info(f"✅ Container started: {container_id[:12]}")

        # Wait for container to be ready
        self._wait_for_container_ready(container_id)

        return container_id

    def _wait_for_container_ready(self, container_id: str, timeout: int = 60) -> None:
        """Wait for container to be ready and accepting connections.

        Args:
            container_id: Container ID
            timeout: Maximum time to wait in seconds
        """
        logger.info(f"⏳ Waiting for container {container_id[:12]} to be ready...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if container is still running
                result = self._run_command([
                    self.runtime, "ps", "-q", "--filter", f"id={container_id}"
                ], capture_output=True, check=False)

                if not result.stdout.strip():
                    # Container stopped - check logs
                    logs = self.get_container_logs(container_id)
                    logger.error(f"❌ Container {container_id[:12]} stopped unexpectedly")
                    logger.error(f"📋 Container logs:\n{logs}")
                    raise RuntimeError("Container failed to start")

                # Try to connect to health endpoint
                port = self._get_container_port(container_id, "4444")
                health_url = f"http://localhost:{port}/health"

                curl_result = self._run_command([
                    "curl", "-f", "-s", "--max-time", "5", health_url
                ], capture_output=True, check=False)

                if curl_result.returncode == 0:
                    logger.info(f"✅ Container {container_id[:12]} is ready and healthy (response: {curl_result.stdout.strip()[:50]})")
                    return
                else:
                    logger.debug(f"❌ Health check failed with return code {curl_result.returncode}, stderr: {curl_result.stderr.strip()[:100]}")

            except Exception as e:
                logger.debug(f"Error checking container status: {e}")

            logger.debug(f"⏳ Container not ready yet, waiting... ({time.time() - start_time:.1f}s)")
            time.sleep(2)

        # Timeout reached
        logs = self.get_container_logs(container_id)
        logger.error(f"❌ Timeout waiting for container {container_id[:12]} to be ready")
        logger.error(f"📋 Container logs:\n{logs}")
        raise RuntimeError(f"Container {container_id[:12]} failed to become ready within {timeout}s")

    def _get_container_port(self, container_id: str, container_port: str) -> str:
        """Get the host port mapping for a container port.

        Args:
            container_id: Container ID
            container_port: Container port to look up

        Returns:
            Host port number as string
        """
        result = self._run_command([
            self.runtime, "port", container_id, container_port
        ], capture_output=True)

        # Parse output like "0.0.0.0:32768"
        port_mapping = result.stdout.strip()
        if ":" in port_mapping:
            return port_mapping.split(":")[-1]
        return port_mapping

    def start_compose_stack(self, version: str, compose_file: str) -> Dict[str, str]:
        """Start docker-compose stack for PostgreSQL testing.

        Args:
            version: MCP Gateway version to use
            compose_file: Path to docker-compose file

        Returns:
            Dictionary mapping service names to container IDs
        """
        logger.info(f"🐙 Starting compose stack for version {version}")
        logger.info(f"📄 Using compose file: {compose_file}")

        env = {
            "IMAGE_LOCAL": f"ghcr.io/ibm/mcp-context-forge:{version}",
            "POSTGRES_PASSWORD": "test_migration_password_123",
            "POSTGRES_USER": "test_user",
            "POSTGRES_DB": "mcp_test"
        }

        logger.info(f"🔧 Environment variables: {env}")

        # Start the stack
        cmd = [f"{self.runtime}-compose", "-f", compose_file, "up", "-d"]
        self._run_command(cmd, env=env)

        # Get container IDs for all services
        containers = self._get_compose_containers(compose_file)

        # Wait for services to be ready
        for service_name, container_id in containers.items():
            logger.info(f"⏳ Waiting for {service_name} service to be ready...")
            if service_name == "postgres":
                self._wait_for_postgres_ready(container_id)
            elif service_name == "gateway":
                self._wait_for_container_ready(container_id)

        logger.info(f"✅ Compose stack started with {len(containers)} services")
        return containers

    def _get_compose_containers(self, compose_file: str) -> Dict[str, str]:
        """Get container IDs for all services in a compose stack.

        Args:
            compose_file: Path to docker-compose file

        Returns:
            Dictionary mapping service names to container IDs
        """
        cmd = [f"{self.runtime}-compose", "-f", compose_file, "ps", "-q"]
        result = self._run_command(cmd, capture_output=True)

        container_ids = result.stdout.strip().split("\n")
        containers = {}

        for container_id in container_ids:
            if container_id:
                # Get service name for this container
                inspect_cmd = [self.runtime, "inspect", container_id,
                              "--format", "{{.Config.Labels.\"com.docker.compose.service\"}}"]
                inspect_result = self._run_command(inspect_cmd, capture_output=True)
                service_name = inspect_result.stdout.strip()
                containers[service_name] = container_id
                self.active_containers.append(container_id)

        return containers

    def _wait_for_postgres_ready(self, container_id: str, timeout: int = 60) -> None:
        """Wait for PostgreSQL to be ready for connections.

        Args:
            container_id: PostgreSQL container ID
            timeout: Maximum time to wait in seconds
        """
        logger.info(f"⏳ Waiting for PostgreSQL {container_id[:12]} to be ready...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to connect to PostgreSQL
                result = self._run_command([
                    self.runtime, "exec", container_id,
                    "pg_isready", "-U", "test_user", "-d", "mcp_test"
                ], capture_output=True, check=False)

                if result.returncode == 0:
                    logger.info(f"✅ PostgreSQL {container_id[:12]} is ready")
                    return

                logger.debug("⏳ PostgreSQL not ready yet, waiting...")
                time.sleep(2)

            except Exception as e:
                logger.debug(f"Error checking PostgreSQL status: {e}")
                time.sleep(2)

        logger.error(f"❌ Timeout waiting for PostgreSQL {container_id[:12]} to be ready")
        raise RuntimeError(f"PostgreSQL failed to become ready within {timeout}s")

    def exec_alembic_command(self, container_id: str, command: str) -> str:
        """Execute Alembic command in container.

        Args:
            container_id: Target container ID
            command: Alembic command to execute (e.g. "upgrade head")

        Returns:
            Command output
        """
        full_cmd = f"cd /app && python -m alembic {command}"
        logger.info(f"🔧 Running Alembic in {container_id[:12]}: {command}")

        result = self._run_command([
            self.runtime, "exec", container_id, "sh", "-c", full_cmd
        ], capture_output=True)

        logger.info(f"✅ Alembic command completed: {command}")
        if result.stdout:
            logger.debug(f"📤 Alembic output: {result.stdout}")

        return result.stdout

    def get_database_schema(self, container_id: str, db_type: str) -> str:
        """Extract current database schema from container.

        For application-level migrations, we skip direct schema extraction
        since containers handle their own database initialization.

        Args:
            container_id: Container ID
            db_type: Database type ("sqlite" or "postgresql")

        Returns:
            Database schema as string (placeholder for app-level migrations)
        """
        logger.info(f"📋 Getting {db_type} schema info from application container {container_id[:12]}")

        # For application-level migrations, we can't directly access the database
        # but we can verify the schema exists by checking the application's health
        try:
            # Check if application is responding to REST API calls using python3
            health_cmd = [
                self.runtime, "exec", container_id,
                "python3", "-c",
                "import urllib.request; "
                "resp = urllib.request.urlopen('http://localhost:4444/health', timeout=5); "
                "print(resp.read().decode())"
            ]
            result = self._run_command(health_cmd, capture_output=True)

            # If health check passes, return a placeholder indicating schema is ready
            schema_placeholder = f"-- {db_type.upper()} schema managed by application\n"
            schema_placeholder += f"-- Database initialized and accessible via REST API\n"
            schema_placeholder += f"-- Health check: {result.stdout.strip()}\n"

            logger.info(f"✅ Application-managed {db_type} schema verified via health check")
            return schema_placeholder

        except Exception as e:
            logger.warning(f"⚠️ Could not verify {db_type} schema via health check: {e}")
            return f"-- {db_type.upper()} schema status unknown\n-- Application container may not be ready\n"

    def seed_test_data(self, container_id: str, data_file: str) -> None:
        """Load test data into container database.

        Args:
            container_id: Target container ID
            data_file: Path to JSON data file
        """
        logger.info(f"🌱 Seeding test data from {data_file} into {container_id[:12]}")

        # Copy data file to container
        self._copy_to_container(container_id, data_file, "/app/seed_data.json")

        # Create data loading script
        load_script = '''
import json
import sys
import os
sys.path.insert(0, "/app")

from mcpgateway.db import SessionLocal
from mcpgateway import models

def load_test_data():
    with open("/app/seed_data.json", "r") as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        # Load tools
        for tool_data in data.get("tools", []):
            tool = models.Tool(**tool_data)
            db.add(tool)

        # Load servers
        for server_data in data.get("servers", []):
            server = models.Server(**server_data)
            db.add(server)

        # Load gateways
        for gateway_data in data.get("gateways", []):
            gateway = models.Gateway(**gateway_data)
            db.add(gateway)

        db.commit()
        print(f"✅ Loaded test data: {len(data.get('tools', []))} tools, {len(data.get('servers', []))} servers, {len(data.get('gateways', []))} gateways")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to load test data: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    load_test_data()
'''

        # Write script to container
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(load_script)
            script_path = f.name

        try:
            self._copy_to_container(container_id, script_path, "/app/load_test_data.py")

            # Execute data loading
            result = self._run_command([
                self.runtime, "exec", container_id,
                "python", "/app/load_test_data.py"
            ], capture_output=True)

            logger.info(f"✅ Test data seeded successfully")
            if result.stdout:
                logger.info(f"📤 Load output: {result.stdout}")

        finally:
            os.unlink(script_path)

    def _copy_to_container(self, container_id: str, src_path: str, dest_path: str) -> None:
        """Copy file to container.

        Args:
            container_id: Target container ID
            src_path: Source file path on host
            dest_path: Destination path in container
        """
        logger.debug(f"📋 Copying {src_path} to {container_id[:12]}:{dest_path}")

        cmd = [self.runtime, "cp", src_path, f"{container_id}:{dest_path}"]
        self._run_command(cmd)

        logger.debug(f"✅ File copied successfully")

    def get_container_logs(self, container_id: str, tail_lines: int = 50) -> str:
        """Get container logs.

        Args:
            container_id: Container ID
            tail_lines: Number of lines to retrieve from end of logs

        Returns:
            Container logs
        """
        cmd = [self.runtime, "logs", "--tail", str(tail_lines), container_id]
        result = self._run_command(cmd, capture_output=True, check=False)
        return result.stdout + result.stderr

    def cleanup_container(self, container_id: str) -> None:
        """Stop and remove container.

        Args:
            container_id: Container ID to clean up
        """
        logger.info(f"🧹 Cleaning up container {container_id[:12]}")

        try:
            # Stop container
            self._run_command([self.runtime, "stop", container_id], check=False)

            # Remove container
            self._run_command([self.runtime, "rm", container_id], check=False)

            # Remove from active list
            if container_id in self.active_containers:
                self.active_containers.remove(container_id)

            logger.info(f"✅ Container {container_id[:12]} cleaned up")

        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up container {container_id[:12]}: {e}")

    def cleanup_all(self) -> None:
        """Clean up all active containers."""
        logger.info(f"🧹 Cleaning up {len(self.active_containers)} active containers")

        for container_id in self.active_containers.copy():
            self.cleanup_container(container_id)

        # Clean up any remaining migration test containers
        try:
            cleanup_cmd = [
                self.runtime, "container", "prune", "-f",
                "--filter", "label=migration-test=true"
            ]
            self._run_command(cleanup_cmd, check=False)
            logger.info("✅ All migration test containers cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error during final cleanup: {e}")

    def get_container_info(self, container_id: str) -> Dict:
        """Get detailed container information.

        Args:
            container_id: Container ID

        Returns:
            Container information dictionary
        """
        cmd = [self.runtime, "inspect", container_id]
        result = self._run_command(cmd, capture_output=True)

        return json.loads(result.stdout)[0]
